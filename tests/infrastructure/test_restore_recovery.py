"""Interrupted restore selection, preservation, repeatability, and retention."""

import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from worklogger.infrastructure.database import MigrationRunner, SQLiteConnectionFactory
from worklogger.infrastructure.database.restore_recovery import (
    inspect_pending_restore,
    prune_restore_backups,
    recover_pending_restore,
)


class RestoreRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.path = self.directory / "worklog.db"
        self.previous = Path(str(self.path) + ".pre_restore")
        self.create(self.previous, "original")
        self.create(self.path, "restored")

    def create(self, path, value):
        factory = SQLiteConnectionFactory(path)
        MigrationRunner(factory).run_pending()
        with factory.transaction() as connection:
            connection.execute("INSERT INTO users(id,username,username_key,password_hash,password_salt,created_at,password_changed_at) "
                               "VALUES(1,'sample','sample','synthetic','synthetic','2030-01-01','2030-01-01')")
            connection.execute("INSERT INTO settings VALUES(1,'sample',?)", (value,))

    def value(self, path):
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            return connection.execute("SELECT value FROM settings WHERE key='sample'").fetchone()[0]

    def archived_database(self, category):
        paths = [path for path in self.directory.glob(f"*.bak_{category}_*")
                 if not path.name.endswith(("-wal", "-shm"))]
        self.assertEqual(len(paths), 1)
        return paths[0]

    def test_explicit_choices_keep_both_database_contents(self):
        self.assertTrue(inspect_pending_restore(self.path).restored_available)
        recover_pending_restore(self.path, "rollback")
        self.assertEqual(self.value(self.path), "original")
        self.assertFalse(self.previous.exists())
        self.assertEqual(self.value(self.archived_database("recovery")), "restored")
        self.assertEqual(self.value(self.archived_database("restore")), "original")
        with self.assertRaisesRegex(ValueError, "restore_pending"):
            recover_pending_restore(self.path, "rollback")

    def test_keep_does_not_change_active_database_and_missing_target_can_roll_back(self):
        recover_pending_restore(self.path, "keep")
        self.assertEqual(self.value(self.path), "restored")
        archived = self.archived_database("restore")
        os.replace(archived, self.previous)
        self.path.unlink()
        options = inspect_pending_restore(self.path)
        self.assertTrue(options.rollback_available)
        self.assertFalse(options.restored_available)
        recover_pending_restore(self.path, "rollback")
        self.assertEqual(self.value(self.path), "original")

    def test_invalid_candidate_is_preserved_and_cannot_be_selected(self):
        self.path.write_bytes(b"synthetic damaged candidate")
        options = inspect_pending_restore(self.path)
        self.assertFalse(options.restored_available)
        with self.assertRaisesRegex(ValueError, "restore_recovery_unavailable"):
            recover_pending_restore(self.path, "keep")
        recover_pending_restore(self.path, "rollback")
        self.assertEqual(self.archived_database("recovery").read_bytes(), b"synthetic damaged candidate")
        self.assertEqual(self.value(self.path), "original")

    def test_archiving_failure_leaves_pending_marker_and_all_copies_recoverable(self):
        replace = os.replace

        def interrupted(source, destination):
            if Path(source) == self.previous:
                raise OSError("synthetic failure")
            return replace(source, destination)

        with (patch("worklogger.infrastructure.database.restore_recovery.os.replace", side_effect=interrupted),
              self.assertRaises(OSError)):
            recover_pending_restore(self.path, "rollback")
        self.assertTrue(self.previous.exists())
        self.assertEqual(self.value(self.previous), "original")
        self.assertEqual(self.value(self.path), "original")
        self.assertEqual(self.value(self.archived_database("recovery")), "restored")
        recover_pending_restore(self.path, "keep")
        self.assertFalse(self.previous.exists())

    def test_rotation_only_removes_generated_restore_snapshots(self):
        generated = []
        for index in range(5):
            candidate = self.path.with_name(self.path.name + ".bak_restore_" + uuid4().hex)
            candidate.write_bytes(b"synthetic snapshot")
            os.utime(candidate, (index + 1, index + 1))
            generated.append(candidate)
        manual = self.path.with_name(self.path.name + ".bak_restore_personal")
        manual.write_bytes(b"retained")
        prune_restore_backups(self.path)
        self.assertEqual([path.exists() for path in generated], [False, False, True, True, True])
        self.assertTrue(manual.exists())
        self.assertTrue(self.previous.exists())
