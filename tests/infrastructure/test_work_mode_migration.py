"""Work arrangement catalog migration preserves records, timers, and undo state."""

from datetime import date, datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from worklogger.domain.worklog.models import WorkMode
from worklogger.domain.worklog.timer_state import EntryTimer, decode_timer, encode_timer
from worklogger.infrastructure.database import SQLiteConnectionFactory, MigrationRunner
from worklogger.infrastructure.database.current_schema import CURRENT_SCHEMA_VERSION, INDEX_STATEMENTS, TABLE_STATEMENTS
from worklogger.infrastructure.repositories import SQLiteAuthRepository, SQLiteWorkLogRepository
from worklogger.infrastructure.security import PBKDF2PasswordHasher


WORKLOG_VERSION_17 = '''CREATE TABLE worklog(
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    d TEXT NOT NULL, start TEXT, end TEXT, "break" REAL NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '', entry_type TEXT NOT NULL DEFAULT 'normal', overnight INTEGER NOT NULL DEFAULT 0,
    started_at TEXT, ended_at TEXT, revision INTEGER NOT NULL DEFAULT 0, capture_id TEXT,
    entry_type_label TEXT NOT NULL DEFAULT '', entry_type_category TEXT NOT NULL DEFAULT '',
    project_id TEXT REFERENCES projects(id), work_item_id TEXT REFERENCES work_items(id),
    project_label TEXT NOT NULL DEFAULT '', work_item_label TEXT NOT NULL DEFAULT '',
    work_mode TEXT CHECK(work_mode IN ('onsite','remote','business_trip','other')))'''


class WorkModeMigrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(self.directory) / "records.db"
        self.factory = SQLiteConnectionFactory(self.path)
        with self.factory.transaction() as connection:
            for name, statement in TABLE_STATEMENTS.items():
                if name != "work_modes":
                    connection.execute(WORKLOG_VERSION_17 if name == "worklog" else statement)
            for statement in INDEX_STATEMENTS:
                if "work_modes_" not in statement:
                    connection.execute(statement)
            connection.execute("INSERT INTO schema_migrations VALUES(17,'entry_classification_and_work_modes',datetime('now'))")
        auth = SQLiteAuthRepository(self.factory, password_hasher=PBKDF2PasswordHasher(iterations=1000))
        self.user = auth.create_user("migration-owner", "example-password", recovery_key=None, is_admin=False)
        from worklogger.domain.worklog.models import EntryType
        self.timer = EntryTimer("existing-timer", datetime(2026, 10, 18, 12, tzinfo=timezone.utc), EntryType.NORMAL, work_mode=WorkMode.REMOTE)
        with self.factory.transaction() as connection:
            connection.execute("INSERT INTO worklog(id,user_id,d,start,end,note,work_mode,revision) VALUES(41,?,'2026-10-18','09:00','10:00','Revised','remote',1)", (self.user.id,))
            current = dict(connection.execute("SELECT * FROM worklog").fetchone())
            before = {**current, "note": "Original", "revision": 0}
            connection.execute("INSERT INTO entry_changes(user_id,operation,before_json,after_json,expected_json) VALUES(?,'update',?,?,?)",
                (self.user.id, json.dumps([before]), json.dumps([current]), json.dumps([current])))
            connection.execute("INSERT INTO settings VALUES(?,'time_entry_timer',?)", (self.user.id, encode_timer(self.timer)))
            connection.execute("UPDATE sqlite_sequence SET seq=77 WHERE name='worklog'")

    def test_upgrade_preserves_snapshots_timer_record_identity_and_sequence(self):
        self.assertEqual(MigrationRunner(self.factory).run_pending(), (CURRENT_SCHEMA_VERSION,))
        repository = SQLiteWorkLogRepository(self.factory)
        record = repository.list_for_day(self.user.id, date(2026, 10, 18))[0]
        self.assertEqual((record.id, record.revision, record.note, record.work_mode), (41, 1, "Revised", WorkMode.REMOTE))
        with self.factory.connection() as connection:
            self.assertEqual(connection.execute("SELECT seq FROM sqlite_sequence WHERE name='worklog'").fetchone()[0], 77)
            self.assertEqual(decode_timer(connection.execute("SELECT value FROM settings WHERE key='time_entry_timer'").fetchone()[0]), self.timer)
            for column in ("before_json", "after_json", "expected_json"):
                self.assertEqual(json.loads(connection.execute(f"SELECT {column} FROM entry_changes").fetchone()[0])[0]["work_mode_label"], "")
        with self.factory.transaction() as connection:
            connection.execute("DELETE FROM settings WHERE key='time_entry_timer'")
        change = repository.latest_change(self.user.id)
        restored = repository.undo_change(self.user.id, change.id)
        self.assertEqual((restored[0].id, restored[0].note), (41, "Original"))
        self.assertEqual(MigrationRunner(self.factory).run_pending(), ())
        self.assertEqual(len(list(self.path.parent.glob("records.db.bak_upgrade_*"))), 1)

    def test_interrupted_upgrade_rolls_back_the_complete_stored_contract(self):
        from worklogger.infrastructure.database.migrations.work_modes import extend_work_modes
        def fail_after_copy(connection):
            extend_work_modes(connection)
            raise OSError("storage unavailable")
        with patch("worklogger.infrastructure.database.migrations.runner.extend_work_modes", fail_after_copy):
            with self.assertRaises(OSError):
                MigrationRunner(self.factory).run_pending()
        with self.factory.connection() as connection:
            self.assertEqual(connection.execute("SELECT version FROM schema_migrations").fetchone()[0], 17)
            self.assertNotIn("work_mode_label", {row[1] for row in connection.execute("PRAGMA table_info(worklog)")})
            self.assertEqual(connection.execute("SELECT note FROM worklog").fetchone()[0], "Revised")
        self.assertTrue(list(self.path.parent.glob("records.db.bak_upgrade_*")))
