"""Explicit development repair must preserve data and remain outside startup."""

import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from scripts.migrate_test_database import main, migrate_test_database
from worklogger.infrastructure.database import MigrationRunner, SQLiteConnectionFactory
from worklogger.infrastructure.database.current_schema import create_current_schema
from worklogger.infrastructure.database.inspection import validate_database_file


class TestDatabaseRepairTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.path = self.directory / "test.db"
        with closing(sqlite3.connect(self.path)) as connection, connection:
            create_current_schema(connection)
            connection.execute("DROP TABLE background_images")
            connection.executemany(
                "INSERT INTO schema_migrations VALUES(?, 'test', '2026-10-11')",
                [(version,) for version in range(1, 14)],
            )
            connection.execute(
                "INSERT INTO users(id,username,username_key,password_hash,password_salt,created_at,password_changed_at) "
                "VALUES(1,'sample','sample','synthetic-hash','synthetic-salt','2026-10-11','2026-10-11')"
            )
            connection.execute("INSERT INTO settings VALUES(1,'sample','preserved')")
            connection.execute("INSERT INTO worklog(user_id,d,note) VALUES(1,'2026-10-11','Content')")
            connection.execute("INSERT INTO daily_notes VALUES(1,'2026-10-11','Independent memo')")

    def test_dry_run_is_read_only_and_startup_still_rejects_source(self):
        before = self.path.read_bytes()
        self.assertEqual(migrate_test_database(self.path), {"status": "ready", "applied": False})
        with self.assertRaisesRegex(ValueError, "database_version_unsupported"):
            MigrationRunner(SQLiteConnectionFactory(self.path)).run_pending()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(list(self.directory.glob("*.bak_*")))

    def test_apply_preserves_committed_wal_rows_and_is_repeatable(self):
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("INSERT INTO settings VALUES(1,'wal_sample','committed')")
            connection.commit()
            result = migrate_test_database(self.path, apply=True)
            self.assertTrue(result["applied"])
            self.assertEqual(result["preserved_rows"]["settings"], 2)
            validate_database_file(self.path)
            with closing(sqlite3.connect(result["backup"])) as backup:
                self.assertEqual(backup.execute("SELECT COUNT(*) FROM settings").fetchone()[0], 2)
                self.assertIsNone(backup.execute("SELECT name FROM sqlite_master WHERE name='background_images'").fetchone())
            self.assertEqual(MigrationRunner(SQLiteConnectionFactory(self.path)).run_pending(), ())
            self.assertEqual(migrate_test_database(self.path, apply=True), {"status": "current", "applied": False})
            self.assertEqual(len(list(self.directory.glob("*.bak_test_v13_*"))), 1)

    def test_other_development_structures_are_not_modified(self):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("ALTER TABLE users RENAME COLUMN display_name TO obsolete_alias")
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            migrate_test_database(self.path, apply=True)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(list(self.directory.glob("*.bak_*")))

    def test_failure_retains_backup_and_rolls_back_all_changes(self):
        def interrupted(connection):
            create_current_schema(connection)
            raise RuntimeError("interrupted")

        with (patch("scripts.migrate_test_database.create_current_schema", side_effect=interrupted),
              self.assertRaisesRegex(RuntimeError, "interrupted")):
            migrate_test_database(self.path, apply=True)
        self.assertEqual(migrate_test_database(self.path)["status"], "ready")
        self.assertEqual(len(list(self.directory.glob("*.bak_test_v13_*"))), 1)
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM worklog").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 13)

    def test_running_desktop_or_pending_restore_prevents_repair(self):
        from worklogger.main import _acquire_instance_lock

        before = self.path.read_bytes()
        lock = _acquire_instance_lock(self.path)
        try:
            with redirect_stderr(StringIO()):
                self.assertEqual(main(["--database", str(self.path), "--apply"]), 1)
        finally:
            lock.unlock()
        Path(str(self.path) + ".pre_restore").touch()
        with self.assertRaisesRegex(ValueError, "restore_pending"):
            migrate_test_database(self.path, apply=True)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(list(self.directory.glob("*.bak_*")))
