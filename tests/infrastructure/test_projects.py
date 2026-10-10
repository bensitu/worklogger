"""Work context preserves ownership, recording, and historical accounting."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from worklogger.app.use_cases.projects import ProjectService
from worklogger.app.use_cases.time_entries import TimeEntryService
from worklogger.domain.projects.models import WorkContext
from worklogger.domain.worklog.models import WorkLog
from worklogger.infrastructure.database import MigrationRunner, SQLiteConnectionFactory
from worklogger.infrastructure.database.migrations.runner import MIGRATION_MODULES
from worklogger.infrastructure.repositories.auth_sqlite import SQLiteAuthRepository
from worklogger.infrastructure.repositories.project_sqlite import SQLiteProjectRepository
from worklogger.infrastructure.repositories.settings_sqlite import SQLiteSettingsRepository
from worklogger.infrastructure.repositories.worklog_sqlite import SQLiteWorkLogRepository
from worklogger.infrastructure.security import PBKDF2PasswordHasher
from worklogger.infrastructure.export.worklog_csv import WorkLogCsvExporter
from worklogger.infrastructure.export.worklog_csv_import import WorkLogCsvImporter
from worklogger.app.use_cases.data_portability import ImportWorkLogsCsvHandler
from worklogger.app.commands.data_portability_commands import ImportWorkLogsCsvCommand
from worklogger.app.use_cases.reports import _template_values


class ProjectTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.factory = SQLiteConnectionFactory(Path(directory) / "worklog.db")
        MigrationRunner(self.factory).run_pending()
        auth = SQLiteAuthRepository(self.factory, password_hasher=PBKDF2PasswordHasher(iterations=1000))
        self.user = auth.create_user("sample", "synthetic-password", recovery_key=None, is_admin=False)
        self.other = auth.create_user("other", "synthetic-password", recovery_key=None, is_admin=False)
        self.projects = ProjectService(self.user.id, SQLiteProjectRepository(self.factory))
        self.records = SQLiteWorkLogRepository(self.factory)
        self.settings = SQLiteSettingsRepository(self.factory)
        self.now = datetime(2026, 10, 10, 9, tzinfo=timezone.utc)

    def recorder(self):
        return TimeEntryService(user_id=self.user.id, repository=self.records, settings=self.settings,
                                local_timezone=timezone.utc, clock=lambda: self.now, projects=self.projects)

    def test_context_ownership_revisions_and_archival_preserve_records(self):
        project = self.projects.save_project("Research", "R1").value
        item = self.projects.save_work_item(project.id, "Review", "https://example.test/issues/1").value
        recorder = self.recorder()
        record = recorder.save_manual(self.now.date(), "09:00", "10:00", "meeting", "Discussion",
                                     context=WorkContext(project.id, item.id)).value
        self.assertEqual(record.context.label, "Research / Review")
        renamed = self.projects.save_project("Development", "R2", project).value
        self.assertFalse(self.projects.save_project("Stale", previous=project).ok)
        self.assertFalse(self.projects.save_project("development").ok)
        other = ProjectService(self.other.id, self.projects.repository)
        self.assertEqual(other.list_projects().value, ())
        self.assertFalse(other.archive_project(renamed).ok)
        with self.assertRaises(ValueError):
            other.resolve(record.context)
        unrelated = self.projects.save_project("Other work").value
        invalid = WorkContext(unrelated.id, item.id)
        self.assertFalse(recorder.save_manual(self.now.date(), "10:00", "11:00", "normal", "Invalid", context=invalid).ok)
        with self.assertRaisesRegex(ValueError, "work_item_unavailable"):
            self.records.save_entry(WorkLog(self.user.id, self.now.date(), "10:00", "11:00", context=invalid))
        with self.assertRaisesRegex(ValueError, "project_unavailable"):
            self.records.save_entry(WorkLog(self.other.id, self.now.date(), "10:00", "11:00", context=record.context))
        self.assertTrue(self.projects.archive_project(renamed).ok)
        self.assertFalse(recorder.save_manual(self.now.date(), "10:00", "11:00", "normal", "New", context=record.context).ok)
        edited = recorder.save_manual(record.day, "09:00", "10:00", "meeting", "Updated", record).value
        self.assertEqual(edited.context, record.context)
        self.assertEqual(edited.worked_hours(), 1)
        self.assertEqual(self.records.get_entry(self.user.id, record.id), edited)
        self.assertTrue(self.projects.save_project("Development").ok)

    def test_timer_context_survives_restart_and_catalog_changes(self):
        project = self.projects.save_project("Research").value
        item = self.projects.save_work_item(project.id, "Reading").value
        recorder = self.recorder()
        self.assertTrue(recorder.start("normal", "Draft", context=WorkContext(project.id, item.id)).ok)
        self.assertTrue(self.projects.archive_work_item(item).ok)
        self.assertTrue(self.projects.archive_project(project).ok)
        restored = self.recorder()
        self.assertFalse(restored.restore_failed)
        self.assertEqual(restored.timer.context.label, "Research / Reading")
        self.now += timedelta(hours=2)
        saved = restored.finish("Completed").value
        self.assertEqual(saved.context, recorder.timer.context)
        self.assertEqual(saved.worked_hours(), 2)
        self.assertIsNone(self.recorder().timer)
        self.assertTrue(restored.save_content("Reviewed", saved).ok)

    def test_context_exports_and_report_totals_preserve_optional_classification(self):
        project = self.projects.save_project("Research").value
        item = self.projects.save_work_item(project.id, "Review").value
        recorder = self.recorder()
        day = self.now.date()
        first = recorder.save_manual(day, "09:00", "11:00", "normal", "Reading", context=WorkContext(project.id, item.id)).value
        recorder.save_manual(day, "11:00", "12:00", "break", "Rest")
        recorder.save_manual(day, "13:00", "14:00", "normal", "Other")
        rows = self.records.list_range(self.user.id, day, day)
        values = _template_values(report_type="daily", start=day, end=day, work_logs=rows,
                                   quick_logs=(), events=(), standard_hours=8, translate=lambda value: value)
        self.assertEqual(values["total_hours"], "3.0")
        self.assertIn("Research: 2.0h", values["projects_summary"])
        self.assertIn("Unclassified: 1.0h", values["projects_summary"])
        self.assertIn("Research / Review", values["task_list"])
        path = Path(self.factory.database_path).parent / "context.csv"
        self.assertTrue(WorkLogCsvExporter().export_work_logs(path, (first,)).ok)
        handler = ImportWorkLogsCsvHandler(importer=WorkLogCsvImporter(), repository=self.records)
        preview = handler.preview(ImportWorkLogsCsvCommand(self.other.id, str(path))).value
        self.assertEqual(preview.errors, ())
        self.assertEqual(preview.rows[0].context.label, first.context.label)
        self.assertIsNone(preview.rows[0].context.project_id)
        self.assertTrue(handler.apply(preview).ok)
        self.assertEqual(self.records.list_for_day(self.other.id, day)[0].worked_hours(), 2)

    def test_context_upgrade_preserves_existing_data_and_repeated_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            factory = SQLiteConnectionFactory(Path(directory) / "previous.db")
            MigrationRunner(factory, migration_modules=MIGRATION_MODULES[:10]).run_pending()
            auth = SQLiteAuthRepository(factory, password_hasher=PBKDF2PasswordHasher(iterations=1000))
            user = auth.create_user("sample", "synthetic-password", recovery_key=None, is_admin=False)
            repository = SQLiteWorkLogRepository(factory)
            original = repository.save_entry(WorkLog(user.id, date(2026, 10, 9), "22:00", "06:00", 1, "Original"))
            self.assertEqual(MigrationRunner(factory).run_pending(), (11,))
            loaded = SQLiteWorkLogRepository(factory).get_entry(user.id, original.id)
            self.assertEqual(loaded, original)
            self.assertEqual(loaded.worked_hours(), 7)
            self.assertEqual(loaded.context, WorkContext())
            self.assertEqual(MigrationRunner(factory).run_pending(), ())
            self.assertEqual(len(tuple(Path(directory).glob("*.bak_upgrade_*"))), 1)
