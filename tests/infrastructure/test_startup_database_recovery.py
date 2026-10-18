"""Database recovery retains originals and publishes only compatible replacements."""

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from tests.infrastructure.test_auth_schema_migration import released_database
from worklogger.app.use_cases.startup_database import RecoverStartupDatabaseHandler
from worklogger.bootstrap import DesktopRuntimeConfig, _prepare_database
from worklogger.infrastructure.database import MigrationRunner, SQLiteConnectionFactory
from worklogger.infrastructure.database.inspection import validate_database_file
from worklogger.infrastructure.database.startup_recovery import SQLiteStartupDatabase, startup_recovery_marker
from worklogger.infrastructure.repositories import SQLiteAuthRepository


class StartupDatabaseRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.path = self.directory / "worklog.db"
        self.original = {suffix: ("Original " + suffix).encode() for suffix in ("", "-wal", "-shm")}
        for suffix, value in self.original.items():
            Path(str(self.path) + suffix).write_bytes(value)
        self.storage = SQLiteStartupDatabase(self.path)

    def assert_original(self):
        for suffix, value in self.original.items():
            self.assertEqual(Path(str(self.path) + suffix).read_bytes(), value)

    def test_invalid_backup_does_not_move_or_replace_original_files(self):
        backup = self.directory / "invalid.db"
        backup.write_bytes(b"Not a SQLite backup")
        self.assertEqual(RecoverStartupDatabaseHandler(self.storage).handle(backup).error.code, "startup_backup_invalid")
        self.assert_original()
        self.assertFalse(startup_recovery_marker(self.path).exists())
        self.assertFalse((self.directory / "database-recovery").exists())

    def test_new_database_retains_all_original_files_and_initializes_without_accounts(self):
        previous = Path(str(self.path) + ".pre_restore")
        previous.write_bytes(b"Earlier original")
        archived = self.storage.replace(None)
        for suffix, value in self.original.items():
            self.assertEqual((archived / (self.path.name + suffix)).read_bytes(), value)
        self.assertEqual((archived / previous.name).read_bytes(), b"Earlier original")
        self.assertFalse(previous.exists())
        validate_database_file(self.path)
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)
        self.assertFalse(startup_recovery_marker(self.path).exists())

    def test_released_backup_migrates_credentials_without_changing_the_backup(self):
        backup = self.directory / "released.db"
        _factory, hasher, user_id = released_database(backup)
        original = backup.read_bytes()
        self.storage.replace(backup)
        self.assertEqual(backup.read_bytes(), original)
        auth = SQLiteAuthRepository(SQLiteConnectionFactory(self.path), password_hasher=hasher)
        self.assertEqual(auth.verify_user("admin", "test-password").id, user_id)

    def test_backup_includes_commits_in_its_wal_without_mixing_original_journals(self):
        backup = self.directory / "backup.db"
        MigrationRunner(SQLiteConnectionFactory(backup)).run_pending()
        with closing(sqlite3.connect(backup)) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("PRAGMA wal_autocheckpoint=0")
            writer.execute("INSERT INTO users(id,username,username_key,password_hash,password_salt,created_at,password_changed_at) "
                           "VALUES(1,'sample','sample','synthetic','synthetic','2030-01-01','2030-01-01')")
            writer.commit()
            self.assertTrue(Path(str(backup) + "-wal").stat().st_size)
            self.storage.replace(backup)
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("SELECT username FROM users").fetchone()[0], "sample")
        self.assertFalse(Path(str(self.path) + "-wal").exists())

    def test_failed_publication_rolls_back_original_files(self):
        import os
        replace = os.replace
        def fail(source, destination):
            if Path(source).parent.name.startswith(".database-preparation-") and Path(destination) == self.path:
                raise OSError("Replacement unavailable")
            return replace(source, destination)
        with patch("worklogger.infrastructure.database.startup_recovery.os.replace", side_effect=fail):
            self.assertFalse(RecoverStartupDatabaseHandler(self.storage).handle().ok)
        self.assert_original()
        self.assertFalse(startup_recovery_marker(self.path).exists())

    def test_interrupted_replacement_blocks_startup_and_preserves_files_across_retry(self):
        import os
        replace = os.replace
        def interrupt(source, destination):
            if Path(source).parent.name.startswith(".database-preparation-") and Path(destination) == self.path:
                raise KeyboardInterrupt
            return replace(source, destination)
        with patch("worklogger.infrastructure.database.startup_recovery.os.replace", side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.storage.replace(None)
        self.assertTrue(startup_recovery_marker(self.path).exists())
        with self.assertRaisesRegex(ValueError, "startup_recovery_pending"):
            _prepare_database(DesktopRuntimeConfig(database_path=self.path))
        retained = next((self.directory / "database-recovery").iterdir())
        self.storage.replace(None)
        self.assertEqual((retained / self.path.name).read_bytes(), self.original[""])
        validate_database_file(self.path)
        self.assertFalse(startup_recovery_marker(self.path).exists())

    def test_registration_policy_blocks_new_database_but_not_backup_restore(self):
        storage = Mock()
        handler = RecoverStartupDatabaseHandler(storage, allow_new_database=False)
        self.assertEqual(handler.handle().error.code, "self_registration_disabled")
        storage.replace.assert_not_called()
        self.assertTrue(handler.handle(self.directory / "backup.db").ok)
