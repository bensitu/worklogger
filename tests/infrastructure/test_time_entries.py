from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from worklogger.app.use_cases.time_entries import EntryTimer, TimeEntryService
from worklogger.app.use_cases.work_types import WorkTypeService
from worklogger.infrastructure.repositories.work_type_sqlite import SQLiteWorkTypeRepository
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
                                local_timezone=timezone.utc, clock=lambda: self.now,
                                work_types=WorkTypeService(self.user.id, SQLiteWorkTypeRepository(self.factory)))

    def test_custom_classifications_keep_accounting_snapshots_across_catalog_changes(self):
        types = self.service.work_types
        work = types.save("Research", "work").value
        saved = self.service.save_manual(self.now.date(), "09:00", "11:00", work.value, "Reading").value
        changed = types.save("Personal break", "break", work).value
        self.assertFalse(types.save("Another name", "work", work).ok)
        self.assertFalse(types.save("personal BREAK", "work").ok)
        rest = self.service.save_manual(self.now.date(), "11:00", "12:00", changed.value, "Rest").value
        self.assertEqual((saved.worked_hours(), rest.worked_hours()), (2, 0))
        self.assertTrue(types.archive(changed).ok)
        self.assertFalse(self.service.save_manual(self.now.date(), "12:00", "13:00", changed.value, "Unavailable").ok)
        edited = self.service.save_manual(saved.day, "09:00", "10:00", work.value, "Updated", saved).value
        loaded = self.repository.get_entry(self.user.id, edited.id)
        self.assertEqual((loaded.work_type.label, loaded.work_type.category, loaded.worked_hours()), ("Research", "work", 1))
        summary = self.repository.list_all(self.user.id)
        data = dashboard_data(summary, year=2026, month=5, scope="monthly", standard_hours=8, monthly_target=160)
        self.assertEqual((data.stats.total_hours, data.stats.rest_days), (1, 1))
        self.assertEqual(dict(data.work_mode_labels)[work.value], "Research")
        other = WorkTypeService(self.user.id + 1, SQLiteWorkTypeRepository(self.factory))
        self.assertEqual(other.list_types().value, ())
        self.assertFalse(other.archive(changed).ok)
        with self.assertRaises(ValueError):
            other.resolve(work.value)

    def test_custom_types_survive_timer_restore_and_csv_round_trip(self):
        definition = self.service.work_types.save("Research", "work").value
        self.assertTrue(self.service.start(definition.value, "Draft").ok)
        self.assertTrue(self.service.work_types.save("Lunch", "break", definition).ok)
        restored = self.make_service()
        self.assertEqual((restored.timer.work_type.label, restored.timer.work_type.category), ("Research", "work"))
        self.now += timedelta(hours=1)
        saved = restored.finish("Completed").value
        csv_path = Path(self.directory.name) / "custom.csv"
        self.assertTrue(WorkLogCsvExporter().export_work_logs(csv_path, (saved,)).ok)
        importer = ImportWorkLogsCsvHandler(importer=WorkLogCsvImporter(), repository=self.repository)
        preview = importer.preview(ImportWorkLogsCsvCommand(self.user.id, str(csv_path))).value
        self.assertEqual(preview.errors, ())
        self.assertEqual(preview.rows[0].work_type.label, "Research")
        self.assertEqual(preview.rows[0].worked_hours(), 1)
        self.assertTrue(importer.apply(preview, overwrite=True).ok)
        self.assertEqual(self.repository.list_for_day(self.user.id, saved.day)[0].work_type.category, "work")

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
        deadline = clicked_end + timedelta(hours=1)
        scheduled = EntryTimer("saved-break", clicked_end, WorkType.BREAK, break_until=deadline,
                               resume_type=WorkType.REMOTE, resume_content="Continued work")
        self.repository.change_timer(self.user.id, None, TimeEntryService._encode(scheduled))
        restored = self.make_service()
        self.now = deadline + timedelta(minutes=15)
        self.assertTrue(restored.advance().ok)
        self.assertEqual(restored.timer.started_at, deadline)
        self.assertEqual(restored.timer.work_type, WorkType.REMOTE)
        self.assertEqual(len(self.repository.list_for_day(self.user.id, self.now.date())), 2)

    def test_fixed_break_is_saved_immediately_with_captured_times_and_no_timer(self):
        clicked = self.now.replace(hour=23, minute=30, second=17)
        self.now = clicked + timedelta(minutes=1)
        result = self.service.take_break(1.75, "Rest", now=clicked)
        self.assertTrue(result.ok, result.error)
        stored = self.repository.list_for_day(self.user.id, clicked.date())[0]
        self.assertEqual((stored.work_type, stored.note, stored.start_time, stored.end_time), (WorkType.BREAK, "Rest", "23:30", "01:15"))
        self.assertEqual(stored.started_at, clicked)
        self.assertEqual(stored.ended_at, clicked + timedelta(hours=1.75))
        self.assertEqual(stored.worked_hours(), 0)
        restored = self.make_service()
        self.assertIsNone(restored.timer)
        self.assertFalse(restored.start("normal", "Overlapping work").ok)
        self.now = stored.ended_at
        self.assertTrue(restored.advance().ok)
        self.assertIsNone(restored.timer)
        self.assertTrue(restored.start("normal", "Next work").ok)

    def test_break_validation_and_failed_writes_preserve_records_and_timer_state(self):
        for hours in (0, -1, 4.1, float("nan"), float("inf")):
            self.assertFalse(self.service.take_break(hours, "Invalid").ok)
        stale = self.make_service()
        self.assertTrue(self.service.start("meeting", "Active").ok)
        self.assertEqual(self.service.take_break(1, "Rest").error.code, "auto_record_already_active")
        self.assertFalse(stale.take_break(1, "Stale request").ok)
        self.assertEqual(self.repository.list_for_day(self.user.id, self.now.date()), ())
        self.assertEqual(self.make_service().timer.work_type, WorkType.MEETING)
        self.now += timedelta(hours=1)
        self.assertTrue(self.service.finish("Completed").ok)
        with patch.object(self.repository._writes, "_change_timer", side_effect=OSError("storage unavailable")):
            self.assertFalse(self.service.take_break(1, "Rest").ok)
        self.assertEqual(len(self.repository.list_for_day(self.user.id, self.now.date())), 1)
        self.assertIsNone(self.make_service().timer)
        self.assertTrue(self.service.take_break(1, "Rest").ok)
        self.assertFalse(self.service.take_break(1, "Overlapping rest").ok)
        self.assertEqual(len(self.repository.list_for_day(self.user.id, self.now.date())), 2)
        saved_break = self.repository.list_for_day(self.user.id, self.now.date())[-1]
        updated = self.service.save_manual(saved_break.day, saved_break.start_time, saved_break.end_time,
                                           "break", "Changed elsewhere", saved_break).value
        early = self.now + timedelta(minutes=1)
        self.assertEqual(self.service.start("normal", "Work", now=early, break_entry=saved_break).error.code, "worklog_entry_conflict")
        self.assertIsNone(self.service.timer)
        self.assertEqual(self.repository.get_entry(self.user.id, updated.id), updated)
        tomorrow = self.now.date() + timedelta(days=1)
        self.assertTrue(self.service.save_manual(tomorrow, "09:00", "10:00", "break", "Manual rest").ok)
        manual_start = self.now.replace(hour=9, minute=30) + timedelta(days=1)
        self.assertEqual(self.service.start("normal", "Work", now=manual_start).error.code, "worklog_entry_overlap")

    def test_confirmed_early_start_changes_break_and_timer_together(self):
        for elapsed in (timedelta(minutes=1), timedelta(0)):
            self.now += timedelta(days=1)
            record = self.service.take_break(1, "Lunch").value
            clicked = self.now + elapsed
            offered = self.service.start("meeting", "Work", now=clicked)
            self.assertEqual(offered.error.code, "fixed_break_active")
            self.assertEqual(offered.error.details["break_entry"], record)
            with patch.object(self.repository._writes, "_change_timer", side_effect=OSError("storage unavailable")):
                self.assertFalse(self.service.start("meeting", "Work", now=clicked, break_entry=record).ok)
            self.assertEqual(self.repository.get_entry(self.user.id, record.id), record)
            self.assertIsNone(self.make_service().timer)
            started = self.service.start("meeting", "Work", now=clicked, break_entry=record)
            self.assertTrue(started.ok, started.error)
            self.assertEqual(self.make_service().timer.started_at, clicked)
            changed = self.repository.get_entry(self.user.id, record.id)
            if elapsed:
                self.assertEqual((changed.started_at, changed.ended_at, changed.note), (record.started_at, clicked, "Lunch"))
                self.assertEqual(changed.revision, record.revision + 1)
            else:
                self.assertIsNone(changed)
            self.assertTrue(self.service.finish("Work", now=clicked + timedelta(minutes=30)).ok)
            entries = self.repository.list_for_day(self.user.id, record.day)
            self.assertEqual(sum(entry.worked_hours() for entry in entries), 0.5)

    def test_failed_automatic_transition_rolls_back_record_and_preserves_timer(self):
        self.service.start("normal", "Retained")
        self.now += timedelta(hours=1)
        with patch.object(self.repository._writes, "_change_timer", side_effect=OSError("storage unavailable")):
            self.assertFalse(self.service.finish("Changed").ok)
        self.assertEqual(self.repository.list_for_day(self.user.id, self.now.date()), ())
        self.assertEqual(self.make_service().timer.content, "Retained")
        self.assertTrue(self.service.finish("Changed").ok)
        self.assertFalse(self.service.finish("Changed").ok)
        self.assertEqual(len(self.repository.list_for_day(self.user.id, self.now.date())), 1)

    def test_daily_schema_migration_preserves_notes_breaks_and_offsets(self):
        path = Path(self.directory.name) / "previous.db"
        factory = SQLiteConnectionFactory(path)
        MigrationRunner(factory, MIGRATION_MODULES[:6]).run_pending()
        auth = SQLiteAuthRepository(factory, password_hasher=PBKDF2PasswordHasher(iterations=1000))
        user = auth.create_user("previous", "example-password", recovery_key=None, is_admin=False)
        repository = SQLiteWorkLogRepository(factory)
        record = WorkLog(user.id, self.now.date(), "09:00", "18:00", 1, "History", WorkType.REMOTE,
                         started_at=self.now, ended_at=self.now + timedelta(hours=9))
        repository.save(record)
        self.assertEqual(MigrationRunner(factory).run_pending(), (7, 8, 9))
        current = SQLiteWorkLogRepository(factory).list_for_day(user.id, record.day)[0]
        self.assertEqual((current.note, current.break_hours, current.worked_hours(), current.started_at), ("History", 1, 8, record.started_at))
        self.assertTrue(list(path.parent.glob("previous.db.bak_upgrade_*")))
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
