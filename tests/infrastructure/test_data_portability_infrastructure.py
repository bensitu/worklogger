from __future__ import annotations

from dataclasses import replace
from datetime import date
from zoneinfo import ZoneInfo
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
from worklogger.domain.worklog.models import WorkLog, EntryType, WorkMode
from worklogger.domain.worklog.rules import shift_datetimes
from worklogger.infrastructure.backup import SQLiteBackupService
from worklogger.infrastructure.backup import sqlite_backup
from worklogger.infrastructure.database import MigrationRunner, SQLiteConnectionFactory
from worklogger.infrastructure.database.migrations.runner import MIGRATION_VERSIONS
from worklogger.infrastructure.export import (
    WorkLogCsvExporter,
    WorkLogCsvImporter,
    WorkLogIcsExporter,
)
from worklogger.infrastructure.repositories import SQLiteAuthRepository, SQLiteWorkLogRepository
from worklogger.infrastructure.security import PBKDF2PasswordHasher


class DataPortabilityInfrastructureTests(unittest.TestCase):
    def test_cancelled_import_parsing_and_preview_do_not_change_records(self):
        from worklogger.app.commands.calendar_commands import ImportCalendarEventsCommand
        from worklogger.app.job_runner import CancellationToken
        from worklogger.app.use_cases.calendar import ImportCalendarEventsHandler
        from worklogger.domain.shared.errors import CancellationError
        from worklogger.infrastructure.calendar.ics_import import IcsCalendarImporter
        from worklogger.infrastructure.repositories import SQLiteCalendarEventRepository

        user = self.register_user("cancelled-import")
        csv_source = Path(self._tempdir.name) / "cancelled.csv"
        csv_source.write_text("date,start,end\n2026-05-01,09:00,10:00\n2026-05-02,09:00,10:00\n", encoding="utf-8")
        ics_source = Path(self._tempdir.name) / "cancelled.ics"
        ics_source.write_text("BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:one\nDTSTART:20260501T090000\nDTEND:20260501T100000\nSUMMARY:Meeting\nEND:VEVENT\nEND:VCALENDAR\n", encoding="utf-8")
        records = SQLiteWorkLogRepository(self.factory)
        calendar = SQLiteCalendarEventRepository(self.factory)
        calls = []

        def is_cancelled():
            calls.append(True)
            return len(calls) >= 3

        for importer, source, method in ((WorkLogCsvImporter(), csv_source, "parse"),
                                          (IcsCalendarImporter(), ics_source, "read_events")):
            calls.clear()
            result = getattr(importer, method)(source, user_id=user, is_cancelled=is_cancelled)
            self.assertIsInstance(result.error, CancellationError)

        token = CancellationToken()
        csv_handler = ImportWorkLogsCsvHandler(importer=WorkLogCsvImporter(), repository=records)
        preview = csv_handler.preview(ImportWorkLogsCsvCommand(user, csv_source)).value
        token.cancel()
        result = csv_handler.apply(preview, cancellation=token)
        self.assertIsInstance(result.error, CancellationError)
        result = ImportCalendarEventsHandler(calendar, IcsCalendarImporter()).handle(
            ImportCalendarEventsCommand(user, ics_source, cancellation=token))
        self.assertIsInstance(result.error, CancellationError)
        self.assertEqual(records.list_all(user), ())
        self.assertEqual(calendar.count(user), 0)

    def test_daily_saves_keep_record_content_separate_from_notes_and_check_previous_content(self):
        from worklogger.infrastructure.repositories import SQLiteDailyNoteRepository
        user = self.register_user("content-owner")
        repository = SQLiteWorkLogRepository(self.factory)
        notes = SQLiteDailyNoteRepository(self.factory)
        day = date(2026, 5, 1)
        repository.save(WorkLog(user, day, note="First"))
        repository.save(WorkLog(user, day, note="Second"), expected_note="First")
        self.assertEqual(notes.get_for_day(user, day).content, "Second")
        repository.save(WorkLog(user, day, "09:00", "10:00", note="Record content"))
        repository.save(WorkLog(user, day, "09:00", "10:00", note="Edited"), expected_note="Record content")
        self.assertEqual(notes.get_for_day(user, day).content, "Second")
        self.assertEqual([row.note for row in repository.list_export_rows(user)], ["Edited", "Second"])
        with self.assertRaisesRegex(ValueError, "note_conflict"):
            repository.save(WorkLog(user, day, "09:00", "10:00", note="Stale"), expected_note="Record content")
        self.assertEqual(repository.get_for_day(user, day).note, "Edited")

    def test_untimed_csv_records_retain_deducted_break_hours(self):
        from worklogger.infrastructure.repositories import SQLiteDailyNoteRepository
        user = self.register_user("deduction-owner")
        path = Path(self._tempdir.name) / "deductions.csv"
        path.write_text("date,start,end,break,note,entry_type\n2026-05-01,,,1.5,Historical deduction,normal\n", encoding="utf-8")
        repository = SQLiteWorkLogRepository(self.factory)
        result = ImportWorkLogsCsvHandler(importer=WorkLogCsvImporter(), repository=repository).handle(
            ImportWorkLogsCsvCommand(user, path))
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.value.imported_count, 1)
        self.assertEqual(repository.list_for_day(user, date(2026, 5, 1))[0].break_hours, 1.5)
        self.assertEqual(SQLiteDailyNoteRepository(self.factory).get_for_day(user, date(2026, 5, 1)).content, "")

    def test_csv_matching_uses_captured_instants_for_repeated_clock_hours(self):
        from datetime import datetime
        user = self.register_user("repeated-hour")
        repository = SQLiteWorkLogRepository(self.factory)
        day, zone = date(2026, 11, 1), ZoneInfo("America/New_York")
        records = [WorkLog(user, day, "01:15", "01:45", note=f"Occurrence {fold}",
            started_at=datetime(2026, 11, 1, 1, 15, tzinfo=zone, fold=fold),
            ended_at=datetime(2026, 11, 1, 1, 45, tzinfo=zone, fold=fold)) for fold in (0, 1)]
        for record in records:
            repository.save_entry(record)
        from dataclasses import replace
        repository.import_many((replace(records[1], note="Imported second occurrence"),), overwrite=True)
        self.assertEqual([record.note for record in repository.list_for_day(user, day)],
                         ["Occurrence 0", "Imported second occurrence"])

    def test_restore_requires_confirmed_delete_journal_mode(self):
        from unittest.mock import Mock
        connection = Mock()
        connection.execute.return_value.fetchone.return_value = ("wal",)
        with self.assertRaisesRegex(ValueError, "restore_database_busy"):
            sqlite_backup._use_delete_journal(connection)

    def test_offset_timestamps_survive_storage_csv_and_calendar_export(self) -> None:
        user_id = self.register_user("timestamp-user")
        day = date(2026, 3, 7)
        started, ended = shift_datetimes(day, "22:00", "06:00", ZoneInfo("America/New_York"))
        repository = SQLiteWorkLogRepository(self.factory)
        repository.save(WorkLog(user_id, day, "22:00", "06:00", 1, started_at=started, ended_at=ended))
        loaded = repository.get_for_day(user_id, day)
        self.assertEqual(loaded.worked_hours(), 6)
        destination = Path(self._tempdir.name) / "timestamps.csv"
        self.assertTrue(WorkLogCsvExporter().export_work_logs(destination, (loaded,)).ok)
        parsed = WorkLogCsvImporter().parse(destination, user_id).value.rows[0]
        self.assertEqual(parsed.started_at, started)
        self.assertEqual(parsed.ended_at, ended)
        imported = ImportWorkLogsCsvHandler(importer=WorkLogCsvImporter(), repository=repository).handle(
            ImportWorkLogsCsvCommand(user_id, destination, overwrite_existing=True))
        self.assertTrue(imported.ok, imported.error)
        self.assertEqual(repository.get_for_day(user_id, day).worked_hours(), 6)
        exported = WorkLogIcsExporter().export_work_logs((loaded,)).value
        self.assertIn("DTSTART:20260308T030000Z", exported)
        self.assertIn("DTEND:20260308T100000Z", exported)

    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tempdir.cleanup)
        self.db_path = str(Path(self._tempdir.name) / "worklog.db")
        self.factory = SQLiteConnectionFactory(self.db_path)
        self.assertEqual(MigrationRunner(self.factory).run_pending(), MIGRATION_VERSIONS)

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
        entry_type: str = EntryType.NORMAL.value,
    ) -> None:
        saved = SaveWorkLogHandler(SQLiteWorkLogRepository(self.factory)).handle(
            SaveWorkLogCommand(
                user_id=user_id,
                day=day,
                start_time=start_time,
                end_time=end_time,
                break_hours=break_hours,
                note=note,
                entry_type=entry_type,
            )
        )
        self.assertTrue(saved.ok, saved.error)

    def test_sqlite_backup_and_restore_round_trip_preserves_backup_snapshot(self) -> None:
        user_id = self.register_user("alice")
        self.save_work_log(user_id, date(2026, 4, 20), note="Before backup")
        service = SQLiteBackupService(self.factory, expected_username="ALICE")
        backup_path = Path(self._tempdir.name) / "backup" / "worklog-backup.db"
        with self.factory.transaction() as connection:
            connection.executemany("INSERT INTO settings(user_id,key,value) VALUES(?,?,?)", (
                (user_id, "secret:ai_api_key", "encrypted test value"),
                (user_id, "ai_api_key", "previous test value"),
                (user_id, "dark_mode", "1")))

        from worklogger.infrastructure.backup.sqlite_backup import create_database_snapshot

        def create_snapshot(source, destination):
            if destination.parent == backup_path.parent:
                self.assertEqual(source.execute(
                    "SELECT COUNT(*) FROM settings WHERE key LIKE 'secret:%' OR key='ai_api_key'"
                ).fetchone()[0], 0)
            return create_database_snapshot(source, destination)

        with patch("worklogger.infrastructure.backup.sqlite_backup.create_database_snapshot", side_effect=create_snapshot):
            backed_up = service.backup_database(backup_path)

        self.assertTrue(backed_up.ok, backed_up.error)
        self.assertTrue(backup_path.is_file())
        with closing(sqlite3.connect(backup_path)) as snapshot:
            settings = dict(snapshot.execute("SELECT key,value FROM settings WHERE user_id=?", (user_id,)))
            self.assertNotIn("secret:ai_api_key", settings)
            self.assertNotIn("ai_api_key", settings)
            self.assertEqual(settings["dark_mode"], "1")
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

        with source_factory.connection(write=True) as live:
            live.execute("PRAGMA wal_autocheckpoint=0")
            live.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            main_file = source.read_bytes()
            live.execute("UPDATE worklog SET note='Committed update'")
            live.execute(
                'INSERT INTO worklog(user_id, d, start, end, "break", note, entry_type) '
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
        self.assertEqual(MigrationRunner(other_factory).run_pending(), MIGRATION_VERSIONS)
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

    def test_worklog_csv_export_preserves_column_contract(self) -> None:
        destination = Path(self._tempdir.name) / "exports" / "worklogs.csv"
        rows = (
            WorkLog(
                user_id=1,
                day=date(2026, 4, 20),
                start_time="22:00",
                end_time="09:00",
                break_hours=1.0,
                note="Night, shift",
                entry_type=EntryType.NORMAL,
            ),
            WorkLog(
                user_id=1,
                day=date(2026, 4, 21),
                break_hours=0.0,
                note="Leave",
                entry_type=EntryType.PAID_LEAVE,
            ),
        )

        result = WorkLogCsvExporter().export_work_logs(destination, rows)

        self.assertTrue(result.ok, result.error)
        with destination.open("r", encoding="utf-8-sig", newline="") as handle:
            exported = list(csv.reader(handle))
        self.assertEqual(
            exported,
            [
                ["date", "start", "end", "break", "note", "entry_type"],
                ["2026-04-20", "22:00", "09:00", "1.0", "Night, shift", "normal"],
                ["2026-04-21", "", "", "0.0", "Leave", "paid_leave"],
            ],
        )
        self.assertTrue(WorkLogCsvExporter().export_work_logs(destination, (replace(rows[0], work_mode=WorkMode.REMOTE), rows[1])).ok)
        with destination.open("r", encoding="utf-8-sig", newline="") as handle:
            extended = list(csv.reader(handle))
        self.assertEqual(extended[0], exported[0] + ["work_mode"])
        self.assertEqual([row[-1] for row in extended[1:]], ["remote", ""])
        parsed = WorkLogCsvImporter().parse(destination, 1).value
        self.assertEqual(tuple(row.work_mode for row in parsed.rows), (WorkMode.REMOTE, None))

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
        self.assertIsNone(imported.work_mode)
        self.assertEqual(leave.entry_type, EntryType.PAID_LEAVE)

    def test_csv_validation_limits_conflicts_and_atomic_import(self):
        user = self.register_user("alice")
        repository = SQLiteWorkLogRepository(self.factory)
        source = Path(self._tempdir.name) / "import.csv"
        source.write_text("date,start,end,break,note,entry_type,work_mode\n"
                          "2026/4/20,09:00,18:00,1,Valid,normal,remote\n"
                          "2026-04-21,09:00,18:00,nan,Invalid,normal,\n"
                          "2026-04-22,,,0,Invalid,unknown,\n"
                          "2026-04-23,09:00,10:00,0,Invalid,normal,hybrid\n"
                          "2026-04-24,09:00,10:00,0,Invalid,paid_leave,remote\n", encoding="utf-8")
        handler = ImportWorkLogsCsvHandler(importer=WorkLogCsvImporter(), repository=repository)
        command = ImportWorkLogsCsvCommand(user, source)
        preview = handler.preview(command).value
        self.assertEqual((len(preview.rows), len(preview.errors), preview.existing_date_count), (1, 4, 0))
        self.assertEqual(preview.rows[0].work_mode, WorkMode.REMOTE)
        self.assertTrue(handler.apply(preview).ok)
        self.assertEqual(handler.preview(command).value.existing_date_count, 1)
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

    def test_csv_protected_text_round_trips_without_guessing_unmarked_apostrophes(self):
        from worklogger.domain.projects.models import WorkContext
        from worklogger.domain.worklog.models import CustomEntryType
        path = Path(self._tempdir.name) / "protected.csv"
        notes = ("- Task", "=1+1", "+Review", "@Owner", "'=literal", "'ordinary", "Line one\nLine two")
        records = tuple(WorkLog(1, date(2026, 4, index + 1), "09:00", "10:00", note=note,
            entry_type=CustomEntryType("custom:" + "a" * 32, "+Research", "work"),
            context=WorkContext(project_label="=Project", work_item_label="'Item"), work_mode=WorkMode.REMOTE)
            for index, note in enumerate(notes))
        self.assertTrue(WorkLogCsvExporter().export_work_logs(path, records).ok)
        parsed = WorkLogCsvImporter().parse(path, 1).value
        self.assertEqual(parsed.errors, ())
        self.assertEqual(tuple(row.note for row in parsed.rows), notes)
        self.assertTrue(all(row.work_mode == WorkMode.REMOTE for row in parsed.rows))
        self.assertTrue(all((row.entry_type_label, row.project_label, row.work_item_label) ==
                            ("+Research", "=Project", "'Item") for row in parsed.rows))
        path.write_text("DATE,NOTE\n2026-04-20,'=literal\n", encoding="utf-8")
        self.assertEqual(WorkLogCsvImporter().parse(path, 1).value.rows[0].note, "'=literal")

    def test_csv_replacement_modes_preserve_other_periods_and_allow_record_undo(self):
        user = self.register_user("csv-user")
        repository = SQLiteWorkLogRepository(self.factory)
        day = date(2026, 4, 20)
        first = repository.save_entry(WorkLog(user, day, "09:00", "10:00", note="Original"))
        second = repository.save_entry(WorkLog(user, day, "11:00", "12:00", note="Other period"))
        replacement = WorkLog(user, day, "09:00", "10:00", note="Imported")
        repository.import_many((replacement,), overwrite=True)
        self.assertEqual([row.note for row in repository.list_for_day(user, day)], ["Imported", "Other period"])
        change = repository.latest_change(user)
        repository.undo_change(user, change.id)
        self.assertEqual([row.id for row in repository.list_for_day(user, day)], [first.id, second.id])
        with self.assertRaises(ValueError):
            repository.import_many((WorkLog(user, day, "09:30", "10:30"),), overwrite=True)
        self.assertEqual([row.id for row in repository.list_for_day(user, day)], [first.id, second.id])
        repository.import_many((replacement,), overwrite=True, replace_dates=True)
        self.assertEqual([row.note for row in repository.list_for_day(user, day)], ["Imported"])
        repository.undo_change(user, repository.latest_change(user).id)
        self.assertEqual([row.id for row in repository.list_for_day(user, day)], [first.id, second.id])

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
                entry_type=EntryType.NORMAL,
                work_mode=WorkMode.REMOTE,
            ),
            WorkLog(
                user_id=1,
                day=date(2026, 4, 22),
                note="Leave",
                entry_type=EntryType.PAID_LEAVE,
            ),
            WorkLog(
                user_id=1,
                day=date(2026, 4, 23),
                start_time="09:00",
                end_time="18:00",
                break_hours=1.0,
                note="x" * 90,
                entry_type=EntryType.REMOTE,
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
        unfolded = ics.replace("\r\n ", "")
        self.assertIn("DESCRIPTION:Normal \u00b7 Remote\\nAlpha\\; Beta\\, Gamma\\\\Delta\\nNext", unfolded)
        self.assertIn("Legacy classification \u00b7 Remote", unfolded)
        self.assertNotIn("worklogger-1-2026-04-22", ics)
        self.assertIn("\r\n ", ics)
        for line in ics.split("\r\n"):
            if line:
                self.assertLessEqual(len(line.encode("utf-8")), 75)

        written = exporter.write_work_logs(destination, rows)
        self.assertTrue(written.ok, written.error)
        self.assertEqual(destination.read_bytes().decode("utf-8"), ics)


if __name__ == "__main__":
    unittest.main()
