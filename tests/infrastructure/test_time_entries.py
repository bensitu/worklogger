from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from worklogger.app.use_cases.time_entries import TimeEntryService
from worklogger.app.use_cases.data_portability import ImportWorkLogsCsvHandler
from worklogger.app.commands.data_portability_commands import ImportWorkLogsCsvCommand
from worklogger.domain.notes.models import DailyNote
from worklogger.domain.analytics.rules import dashboard_data
from worklogger.domain.worklog.models import WorkLog, WorkType
from worklogger.infrastructure.database.connection import SQLiteConnectionFactory
from worklogger.infrastructure.database.migrations.runner import MIGRATION_MODULES, MigrationRunner
from worklogger.infrastructure.repositories.auth_sqlite import SQLiteAuthRepository
from worklogger.infrastructure.repositories.settings_sqlite import SQLiteSettingsRepository
from worklogger.infrastructure.repositories.worklog_sqlite import SQLiteWorkLogRepository
from worklogger.infrastructure.repositories.note_sqlite import SQLiteDailyNoteRepository
from worklogger.infrastructure.export.worklog_csv import WorkLogCsvExporter
from worklogger.infrastructure.export.worklog_csv_import import WorkLogCsvImporter
from worklogger.infrastructure.export.worklog_ics import WorkLogIcsExporter
from worklogger.infrastructure.security.password_hasher import PBKDF2PasswordHasher


class TimeEntryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "worklog.db"
        self.factory = SQLiteConnectionFactory(self.path)
        MigrationRunner(self.factory).run_pending()
        auth = SQLiteAuthRepository(self.factory, password_hasher=PBKDF2PasswordHasher(iterations=1000))
        self.user = auth.create_user("sample", "example-password", recovery_key=None, is_admin=False)
        self.repository = SQLiteWorkLogRepository(self.factory)
        self.settings = SQLiteSettingsRepository(self.factory)
        self.now = datetime(2026, 5, 20, 9, tzinfo=timezone.utc)
        self.service = self.make_service()

    def make_service(self):
        return TimeEntryService(user_id=self.user.id, repository=self.repository, settings=self.settings,
                                local_timezone=timezone.utc, clock=lambda: self.now)

    def test_multiple_entries_edit_delete_and_daily_statistics(self):
        first = self.service.save_manual(self.now.date(), "09:00", "12:00", "meeting", "Planning").value
        rest = self.service.save_manual(self.now.date(), "12:00", "13:00", "break", "Lunch").value
        last = self.service.save_manual(self.now.date(), "13:00", "18:00", "training", "Practice").value
        self.assertEqual(len({first.id, rest.id, last.id}), 3)
        summary = self.repository.get_for_day(self.user.id, self.now.date())
        self.assertEqual(summary.worked_hours(), 8)
        data = dashboard_data(self.repository.list_all(self.user.id), year=2026, month=5, scope="monthly", standard_hours=7, monthly_target=160)
        self.assertEqual((data.stats.total_hours, data.stats.work_days, data.stats.overtime_hours), (8, 1, 1))
        self.assertEqual(dict(data.work_modes), {"meeting": 3, "training": 5})
        updated = self.service.save_manual(first.day, "09:00", "11:00", "meeting", "Updated", first).value
        self.assertEqual(updated.id, first.id)
        self.assertEqual(updated.revision, 1)
        self.assertFalse(self.service.save_manual(first.day, "09:00", "10:00", "normal", "Stale", first).ok)
        self.assertTrue(self.service.delete(rest).ok)
        self.assertEqual(len(self.repository.list_for_day(self.user.id, first.day)), 2)
        with self.assertRaises(ValueError):
            self.repository.delete_entry(self.user.id + 1, last.id, last.revision)

    def test_overlaps_are_rejected_including_overnight_and_active_timers(self):
        day = self.now.date()
        self.assertTrue(self.service.save_manual(day, "22:00", "06:00", "normal", "Night work").ok)
        self.assertFalse(self.service.save_manual(day + timedelta(days=1), "05:00", "07:00", "meeting", "Overlap").ok)
        self.assertTrue(self.service.save_manual(day + timedelta(days=1), "06:00", "07:00", "meeting", "Adjacent").ok)
        self.assertTrue(self.service.start("normal", "Active").ok)
        self.assertFalse(self.service.save_manual(day, "10:00", "11:00", "normal", "Reserved").ok)
        self.assertTrue(self.service.save_manual(day, "07:00", "09:00", "normal", "Before timer").ok)

    def test_automatic_recording_restores_content_and_saves_time_on_finish(self):
        clicked_start = self.now
        self.now += timedelta(minutes=1)
        self.assertTrue(self.service.start("meeting", "Initial", now=clicked_start).ok)
        self.assertTrue(self.service.save_content("Updated").ok)
        self.assertEqual(self.repository.list_for_day(self.user.id, self.now.date()), ())
        resumed = self.make_service()
        self.assertEqual(resumed.timer.content, "Updated")
        clicked_end = clicked_start + timedelta(hours=2)
        self.now = clicked_end + timedelta(minutes=1)
        saved = resumed.finish("Final", now=clicked_end).value
        self.assertEqual((saved.note, saved.worked_hours()), ("Final", 2))
        self.assertIsNone(self.make_service().timer)
        updated = resumed.save_content("Edited after stopping", saved).value
        self.assertEqual(updated.id, saved.id)
        self.assertEqual(len(self.repository.list_for_day(self.user.id, self.now.date())), 1)

    def test_default_break_creates_distinct_records_and_resumes_original_activity(self):
        self.service.start("normal", "Project")
        self.now += timedelta(hours=3)
        self.assertTrue(self.service.take_break(1, "Project").ok)
        resumed = self.make_service()
        self.assertEqual(resumed.timer.work_type, WorkType.BREAK)
        self.now += timedelta(hours=1, minutes=15)
        self.assertTrue(resumed.advance().ok)
        self.assertEqual(resumed.timer.work_type, WorkType.NORMAL)
        self.assertEqual(resumed.timer.started_at.hour, 13)
        self.now = self.now.replace(hour=18, minute=0)
        self.assertTrue(resumed.finish("Delivery").ok)
        entries = self.repository.list_for_day(self.user.id, self.now.date())
        self.assertEqual([entry.work_type for entry in entries], [WorkType.NORMAL, WorkType.BREAK, WorkType.NORMAL])
        self.assertEqual(self.repository.get_for_day(self.user.id, self.now.date()).worked_hours(), 8)

    def test_failed_automatic_transition_rolls_back_record_and_preserves_timer(self):
        self.service.start("normal", "Retained")
        self.now += timedelta(hours=1)
        with patch.object(self.repository, "_change_timer", side_effect=OSError("storage unavailable")):
            self.assertFalse(self.service.finish("Changed").ok)
        self.assertEqual(self.repository.list_for_day(self.user.id, self.now.date()), ())
        self.assertEqual(self.make_service().timer.content, "Retained")
        self.assertTrue(self.service.finish("Changed").ok)
        self.assertFalse(self.service.finish("Changed").ok)
        self.assertEqual(len(self.repository.list_for_day(self.user.id, self.now.date())), 1)

    def test_daily_schema_migration_preserves_notes_breaks_and_offsets(self):
        path = Path(self.directory.name) / "previous.db"
        factory = SQLiteConnectionFactory(path)
        MigrationRunner(factory, MIGRATION_MODULES[:-1]).run_pending()
        auth = SQLiteAuthRepository(factory, password_hasher=PBKDF2PasswordHasher(iterations=1000))
        user = auth.create_user("previous", "example-password", recovery_key=None, is_admin=False)
        repository = SQLiteWorkLogRepository(factory)
        record = WorkLog(user.id, self.now.date(), "09:00", "18:00", 1, "History", WorkType.REMOTE,
                         started_at=self.now, ended_at=self.now + timedelta(hours=9))
        repository.save(record)
        self.assertEqual(MigrationRunner(factory).run_pending(), (7,))
        current = SQLiteWorkLogRepository(factory).list_for_day(user.id, record.day)[0]
        self.assertEqual((current.note, current.break_hours, current.worked_hours(), current.started_at), ("History", 1, 8, record.started_at))
        self.assertTrue(list(path.parent.glob("previous.db.bak_entries_*")))
        self.assertEqual(MigrationRunner(factory).run_pending(), ())

    def test_portability_preserves_periods_types_notes_and_distinct_calendar_identifiers(self):
        day = self.now.date()
        for start, end, kind, content in (("09:00", "12:00", "meeting", "Planning"),
                                         ("12:00", "13:00", "break", "Lunch"),
                                         ("13:00", "17:00", "other", "Practice")):
            self.assertTrue(self.service.save_manual(day, start, end, kind, content).ok)
        SQLiteDailyNoteRepository(self.factory).save(DailyNote(self.user.id, day, "Independent daily note"))
        path = Path(self.directory.name) / "records.csv"
        records = self.repository.list_export_rows(self.user.id)
        self.assertTrue(WorkLogCsvExporter().export_work_logs(path, records).ok)
        auth = SQLiteAuthRepository(self.factory, password_hasher=PBKDF2PasswordHasher(iterations=1000))
        other = auth.create_user("other", "example-password", recovery_key=None, is_admin=False)
        importer = ImportWorkLogsCsvHandler(importer=WorkLogCsvImporter(), repository=self.repository)
        preview = importer.preview(ImportWorkLogsCsvCommand(other.id, path)).value
        self.assertFalse(preview.errors)
        self.assertEqual(len(preview.rows), 4)
        self.assertTrue(importer.apply(preview).ok)
        self.assertEqual(self.repository.get_for_day(other.id, day).worked_hours(), 7)
        self.assertEqual(self.repository.list_for_day(other.id, day)[-1].work_type, WorkType.OTHER)
        self.assertEqual(SQLiteDailyNoteRepository(self.factory).get_for_day(other.id, day).content, "Independent daily note")
        exported = WorkLogIcsExporter().export_work_logs(self.repository.list_all(self.user.id)).value
        identifiers = [line for line in exported.splitlines() if line.startswith("UID:")]
        self.assertEqual(len(identifiers), 3)
        self.assertEqual(len(set(identifiers)), 3)
