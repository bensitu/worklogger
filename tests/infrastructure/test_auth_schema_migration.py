"""Released account import preserves credentials and rejects unsafe conversion."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from tests.infrastructure.schema_samples import create_released_database
from worklogger.infrastructure.database import (
    MigrationRunner,
    SQLiteConnectionFactory,
    released_import,
)
from worklogger.infrastructure.database.migrations.runner import MIGRATION_VERSIONS
from worklogger.infrastructure.repositories import SQLiteAuthRepository


def released_database(path: Path, *, iterations: int = 1000):
    factory = SQLiteConnectionFactory(path)
    hasher, user_id = create_released_database(factory, iterations=iterations)
    with factory.transaction() as connection:
        connection.execute('INSERT INTO worklog(user_id,d,start,end,"break",note,work_type,overnight) VALUES(?,?,?,?,?,?,?,?)',
                           (user_id, "2026-05-21", "09:00", "18:00", 1.0, "Existing work", "normal", 0))
    return factory, hasher, user_id


class AuthSchemaMigrationTests(unittest.TestCase):
    def test_released_credentials_records_and_snapshot_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "worklog.db"
            factory, hasher, user_id = released_database(path)
            with factory.connection() as connection:
                credentials = tuple(connection.execute("SELECT password_hash,salt FROM users").fetchone())
                work = tuple(connection.execute("SELECT * FROM worklog").fetchone())
            self.assertEqual(MigrationRunner(factory).run_pending(), MIGRATION_VERSIONS)
            auth = SQLiteAuthRepository(factory, password_hasher=hasher)
            user = auth.verify_user("ADMIN", "test-password")
            self.assertEqual(user.id, user_id)
            self.assertTrue(user.is_admin)
            self.assertFalse(user.must_change_password)
            self.assertIsNone(auth.verify_user("admin", "wrong-password"))
            with factory.connection() as connection:
                self.assertEqual(tuple(connection.execute("SELECT password_hash,password_salt FROM users").fetchone()), credentials)
                self.assertEqual(tuple(connection.execute('SELECT user_id,d,start,end,"break",note,work_type,overnight FROM worklog').fetchone()), work)
            snapshot = next(path.parent.glob("*.bak_upgrade_*"))
            with closing(sqlite3.connect(snapshot)) as connection:
                self.assertEqual(tuple(connection.execute("SELECT password_hash,salt FROM users").fetchone()), credentials)
                self.assertEqual(tuple(connection.execute("SELECT * FROM worklog").fetchone()), work)
            self.assertEqual(MigrationRunner(factory).run_pending(), ())

    def test_normalized_username_collisions_roll_back_every_change(self):
        with tempfile.TemporaryDirectory() as directory:
            factory, _, _ = released_database(Path(directory) / "accounts.db")
            with factory.transaction() as connection:
                connection.execute("INSERT INTO users(username,password_hash,salt) SELECT 'ADMIN',password_hash,salt FROM users LIMIT 1")
            with self.assertRaisesRegex(ValueError, "username_normalization_conflict"):
                MigrationRunner(factory).run_pending()
            with factory.connection() as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0], 2)
                self.assertIn("salt", {row[1] for row in connection.execute("PRAGMA table_info(users)")})
                self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='schema_migrations'").fetchone())

    def test_backup_failure_and_interrupted_import_preserve_original_schema(self):
        for target in ("snapshot", "conversion"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as directory:
                factory, _, _ = released_database(Path(directory) / "accounts.db")
                if target == "snapshot":
                    failure = patch("worklogger.infrastructure.database.migrations.runner.save_snapshot", side_effect=OSError("unavailable"))
                else:
                    original = released_import.import_released_schema
                    def interrupted(connection, original=original):
                        original(connection)
                        raise OSError("interrupted")
                    failure = patch("worklogger.infrastructure.database.migrations.runner.import_released_schema", side_effect=interrupted)
                with failure, self.assertRaises(OSError):
                    MigrationRunner(factory).run_pending()
                with factory.connection() as connection:
                    self.assertIn("salt", {row[1] for row in connection.execute("PRAGMA table_info(users)")})
                    self.assertEqual(connection.execute("SELECT note FROM worklog").fetchone()[0], "Existing work")
                    self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='schema_migrations'").fetchone())

    def test_snapshot_includes_committed_wal_content(self):
        with tempfile.TemporaryDirectory() as directory:
            factory, _, _ = released_database(Path(directory) / "accounts.db")
            with factory.connection(write=True) as live:
                live.execute("PRAGMA wal_autocheckpoint=0")
                live.execute("UPDATE worklog SET note='Committed WAL content'")
                MigrationRunner(factory).run_pending()
                snapshot = next(Path(directory).glob("*.bak_upgrade_*"))
                with closing(sqlite3.connect(snapshot)) as connection:
                    self.assertEqual(connection.execute("SELECT note FROM worklog").fetchone()[0], "Committed WAL content")
