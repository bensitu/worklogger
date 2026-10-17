from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from worklogger.app.use_cases.time_entries import TimeEntryService
from worklogger.infrastructure.database.connection import SQLiteConnectionFactory
from worklogger.infrastructure.database.migrations.runner import MigrationRunner
from worklogger.infrastructure.repositories.auth_sqlite import SQLiteAuthRepository
from worklogger.infrastructure.repositories.entry_write_session_sqlite import EntryWriteSession
from worklogger.infrastructure.repositories.settings_sqlite import SQLiteSettingsRepository
from worklogger.infrastructure.repositories.worklog_sqlite import SQLiteWorkLogRepository
from worklogger.infrastructure.security.password_hasher import PBKDF2PasswordHasher


class RecordReplacementTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        factory = SQLiteConnectionFactory(Path(directory.name) / "records.db")
        MigrationRunner(factory).run_pending()
        auth = SQLiteAuthRepository(factory, password_hasher=PBKDF2PasswordHasher(iterations=1000))
        self.user = auth.create_user("sample", "example-password", recovery_key=None, is_admin=False)
        self.repository = SQLiteWorkLogRepository(factory)
        self.now = datetime(2026, 10, 5, 19, tzinfo=timezone.utc)
        self.day = self.now.date()
        self.service = TimeEntryService(user_id=self.user.id, repository=self.repository,
            settings=SQLiteSettingsRepository(factory), local_timezone=timezone.utc, clock=lambda: self.now)

    def request(self, start="12:00", end="13:00", original=None):
        result = self.service.save_manual(self.day, start, end, "break", "Lunch", original)
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "worklog_entry_overlap")
        return result.error.details["replacement"]

    def records(self):
        return self.repository.list_for_day(self.user.id, self.day)

    def test_overlap_preview_replacement_and_undo_preserve_existing_work(self):
        old = self.service.save_manual(self.day, "09:00", "18:00", "meeting", "Planning").value
        history = self.service.latest_change().value
        plan = self.request()
        self.assertEqual(self.records(), (old,))
        self.assertEqual(self.service.latest_change().value, history)
        result = self.service.replace_overlap(plan, keep_outside=True)
        self.assertTrue(result.ok, result.error)
        records = self.records()
        self.assertEqual([(item.start_time, item.end_time) for item in records],
                         [("09:00", "12:00"), ("12:00", "13:00"), ("13:00", "18:00")])
        self.assertEqual(sum(item.worked_hours() for item in records), 8)
        self.assertEqual([item.note for item in records], ["Planning", "Lunch", "Planning"])
        self.assertEqual(records[0].id, old.id)
        change = self.service.latest_change().value
        self.assertEqual(change.operation, "replace")
        self.assertTrue(self.service.undo(change.id).ok)
        restored, = self.records()
        self.assertEqual((restored.id, restored.note, restored.start_time, restored.end_time),
                         (old.id, old.note, old.start_time, old.end_time))
        self.assertGreater(restored.revision, old.revision)

    def test_editing_can_replace_multiple_records_and_undo_restores_all(self):
        first = self.service.save_manual(self.day, "09:00", "12:00", "meeting", "Planning").value
        second = self.service.save_manual(self.day, "13:00", "18:00", "training", "Practice").value
        original = self.service.save_manual(self.day, "18:00", "19:00", "break", "Later").value
        plan = self.request("11:00", "14:00", original)
        result = self.service.replace_overlap(plan, keep_outside=False)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(self.records(), (result.value,))
        self.assertEqual(result.value.id, original.id)
        self.assertTrue(self.service.undo(self.service.latest_change().value.id).ok)
        self.assertEqual({item.id for item in self.records()}, {first.id, second.id, original.id})

    def test_stale_preview_and_new_conflicts_leave_records_unchanged(self):
        old = self.service.save_manual(self.day, "09:00", "12:00", "meeting", "Planning").value
        plan = self.request("11:00", "14:00")
        updated = self.service.save_content("Updated elsewhere", old).value
        self.assertEqual(self.service.replace_overlap(plan, keep_outside=True).error.code, "worklog_entry_conflict")
        self.assertEqual(self.records(), (updated,))
        plan = self.request("11:00", "14:00")
        self.assertTrue(self.service.save_manual(self.day, "13:00", "15:00", "training", "New").ok)
        before, history = self.records(), self.service.latest_change().value
        self.assertFalse(self.service.replace_overlap(plan, keep_outside=True).ok)
        self.assertEqual(self.records(), before)
        self.assertEqual(self.service.latest_change().value, history)

    def test_failed_write_and_active_timer_do_not_partially_replace_records(self):
        old = self.service.save_manual(self.day, "09:00", "18:00", "meeting", "Planning").value
        plan = self.request()
        insert = EntryWriteSession.insert
        def interrupted(session, record, **options):
            insert(session, record, **options)
            raise OSError("storage unavailable")
        history = self.service.latest_change().value
        with patch.object(EntryWriteSession, "insert", autospec=True, side_effect=interrupted):
            self.assertFalse(self.service.replace_overlap(plan, keep_outside=True).ok)
        self.assertEqual(self.records(), (old,))
        self.assertEqual(self.service.latest_change().value, history)
        self.assertTrue(self.service.start("normal", "Active").ok)
        result = self.service.replace_overlap(plan, keep_outside=True)
        self.assertEqual(result.error.code, "record_replacement_timer_active")
        self.assertEqual(self.records(), (old,))
        self.assertIsNotNone(self.service.timer)
        self.assertEqual(self.service.save_manual(self.day, "12:00", "13:00", "break", "Lunch").error.code,
                         "record_replacement_timer_active")
