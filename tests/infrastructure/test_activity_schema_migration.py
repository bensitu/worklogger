from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from worklogger.infrastructure.backup import SQLiteBackupService
from worklogger.infrastructure.database import MigrationRunner, SQLiteConnectionFactory
from worklogger.infrastructure.database.migrations import migration_003_activity_events as migration
from worklogger.infrastructure.repositories import ActivityEvent, SQLiteActivityRepository


class ActivitySchemaMigrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "worklog.db"
        self.factory = SQLiteConnectionFactory(self.path, recover_corrupt=False)

    def previous_database(self, *, versioned=True):
        MigrationRunner(self.factory).run_pending()
        with self.factory.transaction() as connection:
            connection.execute("DROP INDEX idx_activity_events_user_created")
            connection.execute("ALTER TABLE activity_events RENAME TO audit_events")
            connection.execute("CREATE INDEX idx_audit_events_user_created ON audit_events(user_id, created_at)")
            connection.execute(
                "INSERT INTO audit_events(id, user_id, event_type, details, created_at) VALUES(?, ?, ?, ?, ?)",
                (42, 7, "login", '{"ok": true}', "2026-05-21T09:00:00+00:00"),
            )
            connection.execute("DELETE FROM schema_migrations WHERE version=3")
            if not versioned:
                connection.execute("DROP TABLE schema_migrations")

    def test_existing_rows_identifiers_index_and_backup_are_preserved(self):
        self.previous_database()
        self.assertEqual(MigrationRunner(self.factory).run_pending(), (3,))
        with self.factory.connection() as connection:
            row = tuple(connection.execute("SELECT * FROM activity_events").fetchone())
            self.assertEqual(row, (42, 7, "login", '{"ok": true}', "2026-05-21T09:00:00+00:00"))
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='audit_events'").fetchone())
            self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE name='idx_activity_events_user_created'").fetchone())
        backups = list(self.path.parent.glob("*.bak_upgrade_*"))
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(backups[0])) as connection:
            self.assertEqual(tuple(connection.execute("SELECT * FROM audit_events").fetchone()), row)
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(MigrationRunner(self.factory).run_pending(), ())
        self.assertEqual(len(list(self.path.parent.glob("*.bak_upgrade_*"))), 1)
        SQLiteActivityRepository(self.factory).record(ActivityEvent("logout", user_id=7))
        with self.factory.connection() as connection:
            self.assertGreater(connection.execute("SELECT MAX(id) FROM activity_events").fetchone()[0], 42)

    def test_unversioned_database_preserves_existing_activity_rows(self):
        self.previous_database(versioned=False)
        self.assertEqual(MigrationRunner(self.factory).run_pending(), (1, 2, 3, 4, 5, 6, 7, 8, 9, 10))
        with self.factory.connection() as connection:
            self.assertEqual(connection.execute("SELECT id FROM activity_events").fetchone()[0], 42)

    def test_new_database_needs_no_compatibility_backup(self):
        self.assertEqual(MigrationRunner(self.factory).run_pending(), (1, 2, 3, 4, 5, 6, 7, 8, 9, 10))
        self.assertFalse(list(self.path.parent.glob("*.bak_*")))

    def test_backup_failure_does_not_change_database(self):
        self.previous_database()
        with patch("worklogger.infrastructure.database.migrations.runner.save_snapshot", side_effect=OSError("backup unavailable")):
            with self.assertRaises(OSError):
                MigrationRunner(self.factory).run_pending()
        with self.factory.connection() as connection:
            self.assertEqual(connection.execute("SELECT id FROM audit_events").fetchone()[0], 42)
            self.assertIsNone(connection.execute("SELECT version FROM schema_migrations WHERE version=3").fetchone())

    def test_conflicting_populated_tables_are_not_merged(self):
        self.previous_database()
        with self.factory.transaction() as connection:
            connection.execute("CREATE TABLE activity_events AS SELECT * FROM audit_events")
        with self.assertRaisesRegex(ValueError, "activity_event_table_conflict"):
            MigrationRunner(self.factory).run_pending()
        with self.factory.connection() as connection:
            for table in ("activity_events", "audit_events"):
                self.assertEqual(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0], 1)
            self.assertIsNone(connection.execute("SELECT version FROM schema_migrations WHERE version=3").fetchone())

    def test_interrupted_rename_rolls_back(self):
        self.check_interrupted_rename(versioned=True)

    def test_interrupted_unversioned_rename_rolls_back(self):
        self.check_interrupted_rename(versioned=False)

    def check_interrupted_rename(self, *, versioned):
        self.previous_database(versioned=versioned)
        original = migration.up

        def interrupted(connection):
            original(connection)
            raise sqlite3.OperationalError("interrupted")

        with patch.object(migration, "up", side_effect=interrupted):
            with self.assertRaises(sqlite3.OperationalError):
                MigrationRunner(self.factory).run_pending()
        with self.factory.connection() as connection:
            self.assertEqual(connection.execute("SELECT id FROM audit_events").fetchone()[0], 42)
            if versioned:
                self.assertIsNone(connection.execute("SELECT version FROM schema_migrations WHERE version=3").fetchone())
            else:
                self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='schema_migrations'").fetchone())
            self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE name='idx_audit_events_user_created'").fetchone())
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='activity_events'").fetchone())

    def test_empty_previous_table_preserves_populated_current_table(self):
        self.previous_database()
        with self.factory.transaction() as connection:
            connection.execute("CREATE TABLE activity_events AS SELECT * FROM audit_events")
            connection.execute("DELETE FROM audit_events")
        self.assertEqual(MigrationRunner(self.factory).run_pending(), (3,))
        with self.factory.connection() as connection:
            self.assertEqual(connection.execute("SELECT id FROM activity_events").fetchone()[0], 42)
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='audit_events'").fetchone())

    def test_index_creation_failure_restores_previous_table_and_index(self):
        self.previous_database()
        original = migration.up

        def reject_index(connection):
            connection.set_authorizer(
                lambda action, *args: sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_CREATE_INDEX else sqlite3.SQLITE_OK
            )
            try:
                original(connection)
            finally:
                connection.set_authorizer(None)

        with patch.object(migration, "up", side_effect=reject_index):
            with self.assertRaises(sqlite3.DatabaseError):
                MigrationRunner(self.factory).run_pending()
        with self.factory.connection() as connection:
            self.assertEqual(connection.execute("SELECT id FROM audit_events").fetchone()[0], 42)
            self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE name='idx_audit_events_user_created'").fetchone())
            self.assertIsNone(connection.execute("SELECT version FROM schema_migrations WHERE version=3").fetchone())

    def test_restore_of_previous_backup_updates_activity_names(self):
        self.previous_database()
        backup = self.path.with_name("previous-backup.db")
        service = SQLiteBackupService(self.factory)
        self.assertTrue(service.backup_database(backup).ok)
        MigrationRunner(self.factory).run_pending()
        SQLiteActivityRepository(self.factory).record(ActivityEvent("logout", user_id=7))

        restored = service.restore_database(backup)

        self.assertTrue(restored.ok, restored.error)
        with self.factory.connection() as connection:
            self.assertEqual([row[0] for row in connection.execute("SELECT id FROM activity_events")], [42])
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='audit_events'").fetchone())
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        with closing(sqlite3.connect(backup)) as connection:
            self.assertEqual(connection.execute("SELECT id FROM audit_events").fetchone()[0], 42)


if __name__ == "__main__":
    unittest.main()
