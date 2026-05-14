from __future__ import annotations

from datetime import date
from pathlib import Path
import csv
import tempfile
import unittest

from worklogger.app.commands.auth_commands import RegisterUserCommand
from worklogger.app.commands.data_portability_commands import ImportWorkLogsCsvCommand
from worklogger.app.commands.work_log_commands import SaveWorkLogCommand
from worklogger.app.use_cases.auth import RegisterUserHandler
from worklogger.app.use_cases.data_portability import ImportWorkLogsCsvHandler
from worklogger.app.use_cases.work_logs import SaveWorkLogHandler
from worklogger.domain.worklog.models import WorkLog, WorkType
from worklogger.infrastructure.backup import SQLiteBackupService
from worklogger.infrastructure.database import MigrationRunner, SQLiteConnectionFactory
from worklogger.infrastructure.export import (
    WorkLogCsvExporter,
    WorkLogCsvImporter,
    WorkLogIcsExporter,
)
from worklogger.infrastructure.repositories import SQLiteAuthRepository, SQLiteWorkLogRepository
from worklogger.infrastructure.security import PBKDF2PasswordHasher


class DataPortabilityInfrastructureTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tempdir.cleanup)
        self.db_path = str(Path(self._tempdir.name) / "worklog.db")
        self.factory = SQLiteConnectionFactory(self.db_path)
        self.assertEqual(MigrationRunner(self.factory).run_pending(), (1,))

    def auth_repository(
        self,
        factory: SQLiteConnectionFactory | None = None,
    ) -> SQLiteAuthRepository:
        return SQLiteAuthRepository(
            factory or self.factory,
            password_hasher=PBKDF2PasswordHasher(
                iterations=1_000,
                legacy_iterations=(100,),
            ),
        )

    def register_user(
        self,
        username: str,
        factory: SQLiteConnectionFactory | None = None,
    ) -> int:
        registered = RegisterUserHandler(self.auth_repository(factory)).handle(
            RegisterUserCommand(username, "secret123")
        )
        self.assertTrue(registered.ok, registered.error)
        assert registered.value is not None
        return registered.value.user.id

    def save_work_log(
        self,
        user_id: int,
        day: date,
        *,
        note: str,
        start_time: str | None = "09:00",
        end_time: str | None = "18:00",
        break_hours: float = 1.0,
        work_type: str = WorkType.NORMAL.value,
    ) -> None:
        saved = SaveWorkLogHandler(SQLiteWorkLogRepository(self.factory)).handle(
            SaveWorkLogCommand(
                user_id=user_id,
                day=day,
                start_time=start_time,
                end_time=end_time,
                break_hours=break_hours,
                note=note,
                work_type=work_type,
            )
        )
        self.assertTrue(saved.ok, saved.error)

    def test_sqlite_backup_and_restore_round_trip_preserves_backup_snapshot(self) -> None:
        user_id = self.register_user("alice")
        self.save_work_log(user_id, date(2026, 4, 20), note="Before backup")
        service = SQLiteBackupService(self.factory, expected_username="alice")
        backup_path = Path(self._tempdir.name) / "backup" / "worklog-backup.db"

        backed_up = service.backup_database(backup_path)

        self.assertTrue(backed_up.ok, backed_up.error)
        self.assertTrue(backup_path.is_file())
        self.assertTrue(service.validate_restore_database(backup_path).ok)

        self.save_work_log(user_id, date(2026, 4, 21), note="After backup")
        restored = service.restore_database(backup_path)

        self.assertTrue(restored.ok, restored.error)
        work_logs = SQLiteWorkLogRepository(self.factory)
        self.assertIsNotNone(work_logs.get_for_day(user_id, date(2026, 4, 20)))
        self.assertIsNone(work_logs.get_for_day(user_id, date(2026, 4, 21)))

    def test_backup_rejects_same_database_path(self) -> None:
        self.register_user("alice")
        service = SQLiteBackupService(self.factory, expected_username="alice")

        result = service.backup_database(Path(self.db_path))

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code if result.error else "", "backup_same_path")

    def test_restore_validation_rejects_mismatched_user_database(self) -> None:
        self.register_user("alice")
        other_path = Path(self._tempdir.name) / "other.db"
        other_factory = SQLiteConnectionFactory(other_path)
        self.assertEqual(MigrationRunner(other_factory).run_pending(), (1,))
        self.register_user("bob", other_factory)
        service = SQLiteBackupService(self.factory, expected_username="alice")

        result = service.validate_restore_database(other_path)

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code if result.error else "", "restore_user_mismatch")

    def test_restore_validation_failure_leaves_current_database_unchanged(self) -> None:
        user_id = self.register_user("alice")
        self.save_work_log(user_id, date(2026, 4, 20), note="Keep me")
        bad_backup = Path(self._tempdir.name) / "bad.db"
        bad_backup.write_bytes(b"not a sqlite database")
        service = SQLiteBackupService(self.factory, expected_username="alice")

        result = service.restore_database(bad_backup)

        self.assertFalse(result.ok)
        self.assertIsNotNone(
            SQLiteWorkLogRepository(self.factory).get_for_day(user_id, date(2026, 4, 20))
        )

    def test_worklog_csv_export_uses_stable_baseline_schema(self) -> None:
        destination = Path(self._tempdir.name) / "exports" / "worklogs.csv"
        rows = (
            WorkLog(
                user_id=1,
                day=date(2026, 4, 20),
                start_time="22:00",
                end_time="09:00",
                break_hours=1.0,
                note="Night, shift",
                work_type=WorkType.NORMAL,
            ),
            WorkLog(
                user_id=1,
                day=date(2026, 4, 21),
                break_hours=0.0,
                note="Leave",
                work_type=WorkType.PAID_LEAVE,
            ),
        )

        result = WorkLogCsvExporter().export_work_logs(destination, rows)

        self.assertTrue(result.ok, result.error)
        with destination.open("r", encoding="utf-8-sig", newline="") as handle:
            exported = list(csv.reader(handle))
        self.assertEqual(
            exported,
            [
                ["date", "start", "end", "break", "note", "work_type"],
                ["2026-04-20", "22:00", "09:00", "1.0", "Night, shift", "normal"],
                ["2026-04-21", "", "", "0.0", "Leave", "paid_leave"],
            ],
        )

    def test_worklog_csv_import_streams_valid_rows_and_reports_row_errors(self) -> None:
        user_id = self.register_user("alice")
        source = Path(self._tempdir.name) / "import.csv"
        source.write_text(
            "\n".join(
                [
                    "date,start,end,break,note,work_type",
                    "2026-04-20,09:00,18:00,1.0,Imported,normal",
                    "bad-date,09:00,18:00,1.0,Bad,normal",
                    "2026-04-21,,,0.0,Leave,paid_leave",
                ]
            ),
            encoding="utf-8",
        )
        work_logs = SQLiteWorkLogRepository(self.factory)
        result = ImportWorkLogsCsvHandler(
            importer=WorkLogCsvImporter(),
            repository=work_logs,
        ).handle(ImportWorkLogsCsvCommand(user_id=user_id, source_path=source))

        self.assertTrue(result.ok, result.error)
        assert result.value is not None
        self.assertEqual(result.value.imported_count, 2)
        self.assertEqual(len(result.value.errors), 1)
        self.assertEqual(result.value.errors[0].row_number, 3)
        imported = work_logs.get_for_day(user_id, date(2026, 4, 20))
        leave = work_logs.get_for_day(user_id, date(2026, 4, 21))
        self.assertIsNotNone(imported)
        self.assertIsNotNone(leave)
        assert imported is not None
        assert leave is not None
        self.assertEqual(imported.note, "Imported")
        self.assertEqual(leave.work_type, WorkType.PAID_LEAVE)

    def test_worklog_ics_export_escapes_folds_and_skips_leave_records(self) -> None:
        destination = Path(self._tempdir.name) / "exports" / "worklogs.ics"
        rows = (
            WorkLog(
                user_id=1,
                day=date(2026, 4, 20),
                start_time="22:00",
                end_time="09:00",
                break_hours=1.0,
                note="Alpha; Beta, Gamma\\Delta\nNext",
                work_type=WorkType.NORMAL,
            ),
            WorkLog(
                user_id=1,
                day=date(2026, 4, 22),
                note="Leave",
                work_type=WorkType.PAID_LEAVE,
            ),
            WorkLog(
                user_id=1,
                day=date(2026, 4, 23),
                start_time="09:00",
                end_time="18:00",
                break_hours=1.0,
                note="x" * 90,
                work_type=WorkType.REMOTE,
            ),
        )
        exporter = WorkLogIcsExporter()

        result = exporter.export_work_logs(rows)

        self.assertTrue(result.ok, result.error)
        ics = result.value or ""
        self.assertTrue(ics.endswith("\r\n"))
        self.assertIn("BEGIN:VCALENDAR\r\n", ics)
        self.assertIn("PRODID:-//WorkLogger//WorkLogger//EN", ics)
        self.assertIn("DTSTART:20260420T220000", ics)
        self.assertIn("DTEND:20260421T090000", ics)
        self.assertIn("SUMMARY:Work 10.0h", ics)
        self.assertIn("DESCRIPTION:Alpha\\; Beta\\, Gamma\\\\Delta\\nNext", ics)
        self.assertNotIn("worklogger-2026-04-22", ics)
        self.assertIn("\r\n ", ics)
        for line in ics.split("\r\n"):
            if line:
                self.assertLessEqual(len(line.encode("utf-8")), 75)

        written = exporter.write_work_logs(destination, rows)
        self.assertTrue(written.ok, written.error)
        self.assertEqual(destination.read_bytes().decode("utf-8"), ics)


if __name__ == "__main__":
    unittest.main()
