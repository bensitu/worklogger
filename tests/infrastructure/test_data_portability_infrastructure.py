from __future__ import annotations

from datetime import date
from contextlib import closing
from pathlib import Path
import csv
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from worklogger.app.commands.auth_commands import RegisterUserCommand
from worklogger.app.commands.data_portability_commands import ImportWorkLogsCsvCommand
from worklogger.app.commands.work_log_commands import SaveWorkLogCommand
from worklogger.app.use_cases.auth import RegisterUserHandler
from worklogger.app.use_cases.data_portability import ImportWorkLogsCsvHandler
from worklogger.app.use_cases.work_logs import SaveWorkLogHandler
from worklogger.domain.worklog.models import WorkLog, WorkType
from worklogger.infrastructure.backup import SQLiteBackupService
from worklogger.infrastructure.backup import sqlite_backup
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
        self.assertEqual(MigrationRunner(self.factory).run_pending(), (1, 2, 3))

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

    def test_database_management_requires_current_administrator_identity(self) -> None:
        admin = self.register_user("administrator")
        member = self.register_user("member")
        destination = Path(self._tempdir.name) / "restricted.db"
        service = SQLiteBackupService(self.factory, expected_username="member", requesting_user_id=member)
        for operation in (service.backup_database, service.validate_restore_database, service.restore_database):
            self.assertEqual(operation(destination).error.code, "admin_required")
        self.assertFalse(destination.exists())
        allowed = SQLiteBackupService(self.factory, expected_username="administrator", requesting_user_id=admin)
        self.assertTrue(allowed.backup_database(destination).ok)
        with self.factory.transaction() as connection:
            connection.execute("UPDATE users SET is_admin=0 WHERE id=?", (admin,))
        self.assertEqual(allowed.restore_database(destination).error.code, "admin_required")

    def test_restore_rejects_changed_identity_and_executable_schema(self) -> None:
        self.register_user("alice")
        source = Path(self._tempdir.name) / "different.db"
        other = SQLiteConnectionFactory(source)
        MigrationRunner(other).run_pending()
        self.register_user("bob", other)
        self.register_user("alice", other)
        service = SQLiteBackupService(self.factory, expected_username="alice")
        self.assertEqual(service.restore_database(source).error.code, "restore_user_mismatch")
        with other.transaction() as connection:
            connection.execute("CREATE VIEW extra AS SELECT * FROM users")
        self.assertEqual(service.validate_restore_database(source).error.code, "restore_schema_invalid")
        self.assertEqual(self.auth_repository().get_by_id(1).username, "alice")

    def test_restore_retains_previous_snapshot_and_interrupted_state(self) -> None:
        user = self.register_user("alice")
        source = Path(self._tempdir.name) / "snapshot.db"
        service = SQLiteBackupService(self.factory, expected_username="alice")
        self.save_work_log(user, date(2026, 4, 20), note="Original")
        self.assertTrue(service.backup_database(source).ok)
        self.save_work_log(user, date(2026, 4, 20), note="Recent")
        self.assertTrue(service.restore_database(source).ok)
        retained = next(Path(self._tempdir.name).glob("worklog.db.bak_restore_*"))
        with closing(sqlite3.connect(retained)) as connection:
            self.assertEqual(connection.execute("SELECT note FROM worklog").fetchone()[0], "Recent")
        previous = Path(self.db_path + ".pre_restore")
        previous.write_bytes(retained.read_bytes())
        self.assertEqual(service.restore_database(source).error.code, "restore_pending")
        self.assertEqual(previous.read_bytes(), retained.read_bytes())

    def test_restore_includes_committed_wal_data_without_uncommitted_changes(self) -> None:
        user_id = self.register_user("alice")
        self.save_work_log(user_id, date(2026, 4, 20), note="Before backup")
        service = SQLiteBackupService(self.factory, expected_username="alice")
        source = Path(self._tempdir.name) / "source #1.db"
        self.assertTrue(service.backup_database(source).ok)
        source_factory = SQLiteConnectionFactory(source, recover_corrupt=False)

        with source_factory.connection() as live:
            live.execute("PRAGMA wal_autocheckpoint=0")
            live.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            main_file = source.read_bytes()
            live.execute("UPDATE worklog SET note='Committed update'")
            live.execute(
                'INSERT INTO worklog(user_id, d, start, end, "break", note, work_type) '
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, "2026-04-21", "09:00", "18:00", 1.0, "Committed insert", "normal"),
            )
            self.assertGreater(Path(str(source) + "-wal").stat().st_size, 0)
            self.assertEqual(source.read_bytes(), main_file)
            live.execute("BEGIN IMMEDIATE")
            live.execute("UPDATE worklog SET note='Uncommitted change'")
            try:
                restored = service.restore_database(source)
                self.assertTrue(restored.ok, restored.error)
                with self.factory.connection() as connection:
                    rows = connection.execute("SELECT d, note FROM worklog ORDER BY d").fetchall()
                    self.assertEqual([tuple(row) for row in rows], [
                        ("2026-04-20", "Committed update"),
                        ("2026-04-21", "Committed insert"),
                    ])
                    self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(source.read_bytes(), main_file)
                self.assertTrue(live.in_transaction)
            finally:
                live.rollback()

    def test_restore_snapshot_failure_preserves_current_database(self) -> None:
        user_id = self.register_user("alice")
        self.save_work_log(user_id, date(2026, 4, 20), note="Before backup")
        service = SQLiteBackupService(self.factory, expected_username="alice")
        source = Path(self._tempdir.name) / "source.db"
        self.assertTrue(service.backup_database(source).ok)
        self.save_work_log(user_id, date(2026, 4, 20), note="Keep current data")
        connect = sqlite3.connect

        class FailingSnapshotConnection(sqlite3.Connection):
            def backup(self, target, **kwargs):
                target.execute("CREATE TABLE incomplete(value TEXT)")
                target.commit()
                raise sqlite3.OperationalError("snapshot write failed")

        def fail_source_backup(database, *args, **kwargs):
            if str(database) == source.resolve().as_uri() + "?mode=ro":
                kwargs["factory"] = FailingSnapshotConnection
            return connect(database, *args, **kwargs)

        with patch.object(sqlite_backup.sqlite3, "connect", side_effect=fail_source_backup):
            result = service.restore_database(source)

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "restore_failed")
        record = SQLiteWorkLogRepository(self.factory).get_for_day(user_id, date(2026, 4, 20))
        self.assertEqual(record.note, "Keep current data")
        self.assertFalse(Path(self.db_path + ".tmp_restore").exists())
        self.assertFalse(Path(self.db_path + ".pre_restore").exists())

    def test_restore_validation_rejects_mismatched_user_database(self) -> None:
        self.register_user("alice")
        other_path = Path(self._tempdir.name) / "other.db"
        other_factory = SQLiteConnectionFactory(other_path)
        self.assertEqual(MigrationRunner(other_factory).run_pending(), (1, 2, 3))
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

    def test_csv_validation_limits_conflicts_and_atomic_import(self):
        user = self.register_user("alice")
        repository = SQLiteWorkLogRepository(self.factory)
        source = Path(self._tempdir.name) / "import.csv"
        source.write_text("date,start,end,break,note,work_type\n"
                          "2026/4/20,09:00,18:00,1,Valid,normal\n"
                          "2026-04-21,09:00,18:00,nan,Invalid,normal\n"
                          "2026-04-22,,,0,Invalid,unknown\n", encoding="utf-8")
        handler = ImportWorkLogsCsvHandler(importer=WorkLogCsvImporter(), repository=repository)
        command = ImportWorkLogsCsvCommand(user, source)
        preview = handler.preview(command).value
        self.assertEqual((len(preview.rows), len(preview.errors), preview.existing_count), (1, 2, 0))
        self.assertTrue(handler.apply(preview).ok)
        self.assertEqual(handler.preview(command).value.existing_count, 1)
        self.assertEqual(handler.handle(command).error.code, "csv_import_conflict")
        self.assertTrue(handler.handle(ImportWorkLogsCsvCommand(user, source, overwrite_existing=True)).ok)
        with self.assertRaises(sqlite3.IntegrityError):
            repository.import_many((WorkLog(user, date(2026, 4, 23)), WorkLog(9999, date(2026, 4, 24))))
        self.assertIsNone(repository.get_for_day(user, date(2026, 4, 23)))
        for importer in (WorkLogCsvImporter(max_bytes=8), WorkLogCsvImporter(max_rows=1)):
            self.assertEqual(importer.parse(source, user).error.code, "csv_file_too_large")
        source.write_bytes(b"date,note\n2026-04-20,\xff\n")
        self.assertFalse(WorkLogCsvImporter(encoding="utf-8").parse(source, user).ok)

    def test_export_preserves_destination_on_failure_and_protects_spreadsheet_text(self):
        path = Path(self._tempdir.name) / "export.csv"
        exporter = WorkLogCsvExporter()
        self.assertTrue(exporter.export_work_logs(path, (WorkLog(1, date(2026, 4, 20), note="=1+1"),)).ok)
        with path.open(encoding="utf-8-sig", newline="") as handle:
            self.assertEqual(list(csv.DictReader(handle))[0]["note"], "'=1+1")
        original = path.read_bytes()

        def broken_rows():
            yield WorkLog(1, date(2026, 4, 21))
            raise OSError("export_unavailable")

        self.assertFalse(exporter.export_work_logs(path, broken_rows()).ok)
        self.assertEqual(path.read_bytes(), original)

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
