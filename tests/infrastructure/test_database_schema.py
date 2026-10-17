"""Current initialization and explicit supported-schema boundaries."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest.mock import patch

from worklogger.domain.reporting.models import Report
from worklogger.domain.worklog.models import EntryType, WorkLog, WorkMode
from worklogger.infrastructure.database import MigrationRunner, SQLiteConnectionFactory
from worklogger.infrastructure.database.current_schema import (
    CURRENT_SCHEMA_VERSION,
    TABLE_STATEMENTS,
    validate_current_schema,
)
from worklogger.infrastructure.database.inspection import validate_database_file
from worklogger.infrastructure.repositories import (
    SQLiteAuthRepository,
    SQLiteReportRepository,
    SQLiteWorkLogRepository,
)
from worklogger.infrastructure.security import PBKDF2PasswordHasher


class DatabaseSchemaTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.factory = SQLiteConnectionFactory(self.directory / "current.db")

    def test_new_schema_is_complete_and_repeated_startup_is_read_only(self):
        self.assertEqual(MigrationRunner(self.factory).run_pending(), (CURRENT_SCHEMA_VERSION,))
        with self.factory.connection() as connection:
            validate_current_schema(connection)
            self.assertEqual({row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}, set(TABLE_STATEMENTS))
        self.assertEqual(MigrationRunner(self.factory).run_pending(), ())
        self.assertFalse(list(self.directory.glob("*.bak_upgrade_*")))

    def test_current_schema_round_trips_work_modes_and_preserves_reports_on_restart(self):
        MigrationRunner(self.factory).run_pending()
        auth = SQLiteAuthRepository(self.factory, password_hasher=PBKDF2PasswordHasher(iterations=1000))
        user = auth.create_user("sample", "synthetic-password", recovery_key=None, is_admin=False)
        auth.set_display_name(user.id, "Mary", expected_display_name="")
        day = date(2026, 10, 11)
        records = SQLiteWorkLogRepository(self.factory)
        entry = records.save_entry(WorkLog(user.id, day, "09:00", "10:00", note="Record content",
                                          entry_type=EntryType.MEETING, work_mode=WorkMode.REMOTE, capture_id="capture"))
        self.assertEqual(records.get_entry(user.id, entry.id), entry)
        self.assertEqual(records.save_entry(replace(entry, id=None)), entry)
        with self.assertRaisesRegex(ValueError, "worklog_entry_conflict"):
            records.save_entry(replace(entry, id=None, work_mode=WorkMode.ONSITE))
        entry = records.save_entry(replace(entry, work_mode=WorkMode.BUSINESS_TRIP))
        reports = SQLiteReportRepository(self.factory)
        report = reports.save(Report(None, user.id, "daily", day, day, "Report content"))
        versions = reports.list_revisions(user.id, report.id)
        self.assertEqual(MigrationRunner(self.factory).run_pending(), ())
        self.assertEqual(records.get_entry(user.id, entry.id), entry)
        self.assertEqual(reports.get_for_period(user.id, "daily", day, day), report)
        self.assertEqual(reports.list_revisions(user.id, report.id), versions)
        self.assertEqual(auth.get_by_id(user.id).display_name, "Mary")
        self.assertFalse(list(self.directory.glob("*.bak_upgrade_*")))

    def test_unversioned_current_database_is_rejected_without_adding_a_ledger(self):
        MigrationRunner(self.factory).run_pending()
        with self.factory.transaction() as connection:
            connection.execute("DROP TABLE schema_migrations")
        with self.assertRaisesRegex(ValueError, "database_schema_unsupported"):
            MigrationRunner(self.factory).run_pending()
        with self.factory.connection() as connection:
            self.assertIsNone(connection.execute("SELECT 1 FROM sqlite_master WHERE name='schema_migrations'").fetchone())

    def test_early_development_ledgers_and_inconsistent_current_schema_are_rejected(self):
        for previous_version, remove_table, expected in ((12, False, "database_version_unsupported"),
                                                       (14, False, "database_version_unsupported"),
                                                       (15, True, "database_version_unsupported"),
                                                       (16, False, "database_version_unsupported"),
                                                       (18, False, "database_version_unsupported"),
                                                       (CURRENT_SCHEMA_VERSION, True, "database_schema_unsupported")):
            path = self.directory / f"unsupported-{previous_version}.db"
            factory = SQLiteConnectionFactory(path)
            MigrationRunner(factory).run_pending()
            with factory.transaction() as connection:
                connection.execute("DELETE FROM schema_migrations")
                connection.execute("INSERT INTO schema_migrations VALUES(?, 'previous', '2026-10-10')", (previous_version,))
                if remove_table:
                    connection.execute("DROP TABLE background_images")
            with self.assertRaisesRegex(ValueError, expected):
                MigrationRunner(factory).run_pending()
            with self.assertRaisesRegex(ValueError, expected):
                validate_database_file(path)
            with factory.connection() as connection:
                self.assertEqual(connection.execute("SELECT version FROM schema_migrations").fetchone()[0], previous_version)
            self.assertFalse(list(self.directory.glob(path.name + ".bak_upgrade_*")))

    def test_failed_initialization_rolls_back_the_entire_schema(self):
        def interrupted(connection):
            connection.execute(TABLE_STATEMENTS["users"])
            raise sqlite3.OperationalError("interrupted")

        with patch("worklogger.infrastructure.database.migrations.runner.create_current_schema", side_effect=interrupted), self.assertRaises(sqlite3.OperationalError):
            MigrationRunner(self.factory).run_pending()
        with self.factory.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0], 0)

    def test_rejected_development_file_is_not_modified_before_detection(self):
        for version in (7, 14, 15, 16):
            with self.subTest(version=version):
                path = self.directory / f"development-{version}.db"
                with closing(sqlite3.connect(path)) as connection, connection:
                    connection.execute(TABLE_STATEMENTS["schema_migrations"])
                    connection.execute("INSERT INTO schema_migrations VALUES(?,'development','2026-10-10')", (version,))
                original = path.read_bytes()
                with self.assertRaisesRegex(ValueError, "database_version_unsupported"):
                    MigrationRunner(SQLiteConnectionFactory(path)).run_pending()
                self.assertEqual(path.read_bytes(), original)
                self.assertFalse(Path(str(path) + "-wal").exists())
                self.assertFalse(Path(str(path) + "-shm").exists())
                self.assertFalse(list(self.directory.glob(path.name + ".bak_upgrade_*")))

    def test_declared_foreign_keys_are_required_even_without_existing_rows(self):
        MigrationRunner(self.factory).run_pending()
        with self.factory.transaction() as connection:
            connection.execute("DROP TABLE worklog")
            connection.execute(TABLE_STATEMENTS["worklog"].replace("REFERENCES users(id) ON DELETE CASCADE", ""))
        with self.assertRaisesRegex(ValueError, "database_schema_unsupported"):
            MigrationRunner(self.factory).run_pending()
