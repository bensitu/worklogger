from contextlib import closing
from datetime import date
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from worklogger.infrastructure.database import MigrationRunner, SQLiteConnectionFactory
from worklogger.infrastructure.database.migrations.runner import MIGRATION_MODULES
from worklogger.infrastructure.database.migrations import migration_002_auth_columns
from worklogger.infrastructure.repositories import SQLiteAuthRepository, SQLiteWorkLogRepository
from worklogger.infrastructure.security import PBKDF2PasswordHasher
from worklogger.domain.worklog.models import WorkLog

INITIAL = "worklogger.infrastructure.database.migrations.migration_001_initial_schema"


def legacy_database(path: Path, *, iterations: int = 1_000):
    factory = SQLiteConnectionFactory(path, recover_corrupt=False)
    MigrationRunner(factory, migration_modules=(INITIAL,)).run_pending()
    hasher = PBKDF2PasswordHasher(iterations=iterations)
    auth = SQLiteAuthRepository(factory, password_hasher=hasher)
    admin = auth.create_user("admin", "test-password", recovery_key="test-recovery", is_admin=True)
    SQLiteWorkLogRepository(factory).save(WorkLog(
        admin.id, date(2026, 5, 21), "09:00", "18:00", 1.0, "Existing work",
    ))
    with factory.transaction(write=True) as connection:
        connection.execute("ALTER TABLE users RENAME COLUMN password_salt TO salt")
        connection.execute("ALTER TABLE users DROP COLUMN must_change_password")
    return factory, hasher, admin.id


class AuthSchemaMigrationTests(unittest.TestCase):
    def test_canonical_username_migration_preserves_accounts_and_rejects_conflicts(self):
        for conflict in (False, True):
            with self.subTest(conflict=conflict), tempfile.TemporaryDirectory() as directory:
                factory = SQLiteConnectionFactory(Path(directory) / "accounts.db")
                MigrationRunner(factory, migration_modules=(INITIAL,)).run_pending()
                auth = SQLiteAuthRepository(factory, password_hasher=PBKDF2PasswordHasher(iterations=1_000))
                user = auth.create_user("Alice", "password", recovery_key=None, is_admin=False)
                if conflict:
                    auth.create_user("alice", "different", recovery_key=None, is_admin=False)
                    with self.assertRaisesRegex(ValueError, "username_normalization_conflict"):
                        MigrationRunner(factory).run_pending()
                    with factory.connection() as connection:
                        self.assertEqual(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0], 2)
                        self.assertNotIn("username_key", {row[1] for row in connection.execute("PRAGMA table_info(users)")})
                else:
                    MigrationRunner(factory).run_pending()
                    auth = SQLiteAuthRepository(factory, password_hasher=PBKDF2PasswordHasher(iterations=1_000))
                    self.assertEqual(auth.verify_user("ＡLICE", "password").id, user.id)
                    self.assertEqual(auth.get_by_username("alice").username, "Alice")
                    with self.assertRaisesRegex(ValueError, "username_exists"):
                        auth.create_user("alice", "different", recovery_key=None, is_admin=False)

    def test_legacy_credentials_and_work_logs_survive_migration_and_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "worklog.db"
            factory, hasher, user_id = legacy_database(path)
            with factory.connection() as connection:
                credentials = tuple(connection.execute("SELECT password_hash, salt FROM users").fetchone())
                work_log = tuple(connection.execute("SELECT * FROM worklog").fetchone())
            self.assertEqual(MigrationRunner(factory).run_pending(), tuple(range(2, len(MIGRATION_MODULES) + 1)))
            auth = SQLiteAuthRepository(factory, password_hasher=hasher)
            user = auth.verify_user("admin", "test-password")
            self.assertIsNotNone(user)
            self.assertEqual(user.id, user_id)
            self.assertTrue(user.is_admin)
            self.assertFalse(user.must_change_password)
            self.assertIsNone(auth.verify_user("admin", "wrong-password"))
            with factory.connection() as connection:
                self.assertEqual(tuple(connection.execute("SELECT password_hash, password_salt FROM users").fetchone()), credentials)
                self.assertEqual(tuple(connection.execute('SELECT user_id,d,start,end,"break",note,work_type,overnight FROM worklog').fetchone()), work_log)
                self.assertEqual(tuple(connection.execute("SELECT started_at,ended_at FROM worklog").fetchone()), (None, None))
            backups = list(path.parent.glob("worklog.db.bak_upgrade_*"))
            self.assertEqual(len(backups), 1)
            with closing(sqlite3.connect(backups[0].as_uri() + "?mode=ro", uri=True)) as backup:
                self.assertEqual(tuple(backup.execute("SELECT password_hash, salt FROM users").fetchone()), credentials)
                self.assertEqual(tuple(backup.execute("SELECT * FROM worklog").fetchone()), work_log)
                self.assertEqual(backup.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(MigrationRunner(factory).run_pending(), ())
            self.assertEqual(len(list(path.parent.glob("worklog.db.bak_upgrade_*"))), 1)
            recovery = auth.change_password(user_id, "test-password", "changed-password")
            self.assertIsNotNone(recovery)
            self.assertIsNotNone(auth.verify_user("admin", "changed-password"))
            self.assertIsNotNone(auth.reset_password_with_recovery("admin", recovery, "reset-password"))
            self.assertIsNotNone(auth.verify_user("admin", "reset-password"))
            self.assertIsNotNone(auth.create_user("second-user", "second-password", recovery_key=None, is_admin=False))

    def test_backup_failure_prevents_schema_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "worklog.db"
            factory, _, _ = legacy_database(path)
            connect = sqlite3.connect

            def fail_backup(database, *args, **kwargs):
                if ".bak_upgrade_" in str(database):
                    raise sqlite3.OperationalError("backup unavailable")
                return connect(database, *args, **kwargs)

            with patch.object(migration_002_auth_columns.sqlite3, "connect", side_effect=fail_backup):
                with self.assertRaises(sqlite3.OperationalError):
                    MigrationRunner(factory).run_pending()
            with factory.connection() as connection:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
                self.assertIn("salt", columns)
                self.assertNotIn("password_salt", columns)
                self.assertNotIn("must_change_password", columns)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0], 1)

    def test_migration_failure_rolls_back_credentials_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            factory, _, _ = legacy_database(Path(directory) / "worklog.db")

            def fail_migration(connection):
                connection.execute("ALTER TABLE users RENAME COLUMN salt TO password_salt")
                raise sqlite3.OperationalError("migration interrupted")

            with patch.object(migration_002_auth_columns, "up", side_effect=fail_migration):
                with self.assertRaises(sqlite3.OperationalError):
                    MigrationRunner(factory).run_pending()
            with factory.connection() as connection:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
                self.assertIn("salt", columns)
                self.assertNotIn("password_salt", columns)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0], 1)

    def test_new_database_does_not_create_unnecessary_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "new.db"
            self.assertEqual(MigrationRunner(SQLiteConnectionFactory(path)).run_pending(), tuple(range(1, len(MIGRATION_MODULES) + 1)))
            self.assertFalse(list(path.parent.glob("*.bak_upgrade_*")))

    def test_legacy_hash_upgrades_only_after_correct_password(self):
        with tempfile.TemporaryDirectory() as directory:
            factory, _, _ = legacy_database(Path(directory) / "worklog.db", iterations=100_000)
            with factory.connection() as connection:
                original = tuple(connection.execute("SELECT password_hash, salt FROM users").fetchone())
            MigrationRunner(factory).run_pending()
            auth = SQLiteAuthRepository(factory)
            self.assertIsNone(auth.verify_user("admin", "wrong-password"))
            with factory.connection() as connection:
                self.assertEqual(tuple(connection.execute("SELECT password_hash, password_salt FROM users").fetchone()), original)
            self.assertIsNotNone(auth.verify_user("admin", "test-password"))
            with factory.connection() as connection:
                upgraded = tuple(connection.execute("SELECT password_hash, password_salt FROM users").fetchone())
            self.assertNotEqual(upgraded, original)
            self.assertFalse(PBKDF2PasswordHasher().verify("test-password", *upgraded).needs_upgrade)

    def test_backup_includes_committed_wal_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "worklog.db"
            factory, _, _ = legacy_database(path)
            with factory.connection() as live:
                live.execute("PRAGMA wal_autocheckpoint=0")
                live.execute("UPDATE worklog SET note=?", ("Committed WAL data",))
                self.assertGreater(Path(str(path) + "-wal").stat().st_size, 0)
                MigrationRunner(factory).run_pending()
                backups = list(path.parent.glob("worklog.db.bak_upgrade_*"))
                self.assertEqual(len(backups), 1)
                with closing(sqlite3.connect(backups[0])) as backup:
                    self.assertEqual(backup.execute("SELECT note FROM worklog").fetchone()[0], "Committed WAL data")
                    self.assertEqual(backup.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_missing_salt_fails_without_resetting_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            factory, _, _ = legacy_database(Path(directory) / "worklog.db")
            with factory.transaction(write=True) as connection:
                connection.execute("ALTER TABLE users DROP COLUMN salt")
                original = tuple(connection.execute("SELECT id, password_hash FROM users").fetchone())
            with self.assertRaisesRegex(ValueError, "auth_schema_missing_password_salt"):
                MigrationRunner(factory).run_pending()
            with factory.connection() as connection:
                self.assertEqual(tuple(connection.execute("SELECT id, password_hash FROM users").fetchone()), original)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0], 1)
