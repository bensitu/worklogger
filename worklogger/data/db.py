"""SQLite database access layer."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import shutil
import sqlite3
import sys
import threading
import time
from datetime import date, datetime, timedelta

from config.constants import (
    DB_FILENAME,
    DEFAULT_ADMIN_USER,
    FORCE_PASSWORD_CHANGE_SETTING_KEY,
    REMEMBER_TOKEN_LIFETIME_DAYS,
)
from core.models import WorkRecord
from core.time_calc import is_overnight_shift


def get_db_path() -> str:
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, DB_FILENAME)


DB_PATH = get_db_path()
_PBKDF2_ITERATIONS = 600_000
_PBKDF2_LEGACY_ITERATIONS = (100_000,)
_WORKLOG_TABLE_NAMES = ("worklog", "worklogs", "work_log")

_CREATE_USERS = """CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    recovery_key_hash TEXT,
    recovery_salt TEXT,
    is_admin INTEGER DEFAULT 0,
    remember_token TEXT,
    remember_token_expires_at TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    password_changed_at TEXT DEFAULT (datetime('now')),
    recovery_key_created_at TEXT
)"""

_CREATE_WORKLOG = """CREATE TABLE IF NOT EXISTS worklog(
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    d TEXT NOT NULL,
    start TEXT,
    end TEXT,
    break REAL,
    note TEXT,
    work_type TEXT DEFAULT 'normal',
    overnight INTEGER DEFAULT 0,
    PRIMARY KEY(user_id, d)
)"""

_CREATE_SETTINGS = """CREATE TABLE IF NOT EXISTS settings(
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT,
    PRIMARY KEY(user_id, key)
)"""

_CREATE_QUICK_LOGS = """CREATE TABLE IF NOT EXISTS quick_logs(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    time TEXT NOT NULL,
    end_time TEXT DEFAULT '',
    description TEXT NOT NULL,
    created_at TEXT NOT NULL
)"""

_CREATE_CALENDAR = """CREATE TABLE IF NOT EXISTS calendar_events(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    start_time TEXT,
    end_time TEXT,
    summary TEXT NOT NULL,
    description TEXT DEFAULT '',
    location TEXT DEFAULT '',
    all_day INTEGER DEFAULT 0,
    source_file TEXT DEFAULT ''
)"""

_CREATE_REPORTS = """CREATE TABLE IF NOT EXISTS reports(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
)"""


class DB:
    def __init__(self, path: str | None = None):
        # _write_lock serialises all write operations so that background
        # threads sharing this DB instance never interleave commits.
        self._write_lock = threading.Lock()
        self.path = path or DB_PATH
        self.conn = self._open_connection(self.path)
        self._migrate()

    @staticmethod
    def _open_connection(path: str) -> sqlite3.Connection:
        try:
            conn = sqlite3.connect(path, timeout=5, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA foreign_keys=ON")
            r = conn.execute("PRAGMA integrity_check").fetchone()
            if r and r[0] != "ok":
                raise sqlite3.DatabaseError(f"Integrity check failed: {r[0]}")
            return conn
        except sqlite3.DatabaseError as exc:
            backup = path + f".bak_{int(time.time())}"
            try:
                if os.path.exists(path):
                    shutil.move(path, backup)
            except Exception:
                pass
            try:
                conn = sqlite3.connect(path, timeout=5, check_same_thread=False)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute("PRAGMA busy_timeout=5000")
                conn.execute("PRAGMA foreign_keys=ON")
                return conn
            except sqlite3.DatabaseError:
                raise sqlite3.DatabaseError(
                    f"Cannot recover database at {path} after error: {exc}"
                ) from exc

    def _migrate(self) -> None:
        """Create current tables and migrate legacy single-user data."""
        with self._write_lock:
            self.conn.execute("PRAGMA foreign_keys=OFF")
            legacy_data_exists = self._legacy_data_exists()
            self.conn.execute(_CREATE_USERS)
            self._migrate_users_table()
            fallback_user_id = self._first_user_id_unlocked()
            created_admin_id: int | None = None
            if fallback_user_id is None and legacy_data_exists:
                created_admin_id = self._create_user_unlocked(
                    DEFAULT_ADMIN_USER,
                    DEFAULT_ADMIN_USER,
                    is_admin=True,
                )
                fallback_user_id = created_admin_id

            self._migrate_worklog_table(fallback_user_id)
            self._migrate_settings_table(fallback_user_id)
            self._migrate_quick_logs_table(fallback_user_id)
            self._migrate_calendar_table(fallback_user_id)
            self._migrate_reports_table(fallback_user_id)

            if created_admin_id is not None:
                self.conn.execute(
                    "INSERT OR REPLACE INTO settings(user_id,key,value) VALUES(?,?,?)",
                    (created_admin_id, FORCE_PASSWORD_CHANGE_SETTING_KEY, "1"),
                )

            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_worklog_user_date ON worklog(user_id,d)"
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_quick_logs_user_date ON quick_logs(user_id,date)"
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_calendar_user_date ON calendar_events(user_id,date)"
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reports_user_type_created "
                "ON reports(user_id,type,created_at DESC)"
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_users_remember_token ON users(remember_token)"
            )
            self.conn.commit()
            self.conn.execute("PRAGMA foreign_keys=ON")

    def _migrate_users_table(self) -> None:
        cols = self._columns("users")
        if "password_changed_at" not in cols:
            self.conn.execute("ALTER TABLE users ADD COLUMN password_changed_at TEXT")
        if "recovery_key_hash" not in cols:
            self.conn.execute("ALTER TABLE users ADD COLUMN recovery_key_hash TEXT")
        if "recovery_salt" not in cols:
            self.conn.execute("ALTER TABLE users ADD COLUMN recovery_salt TEXT")
        if "is_admin" not in cols:
            self.conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
        if "recovery_key_created_at" not in cols:
            self.conn.execute(
                "ALTER TABLE users ADD COLUMN recovery_key_created_at TEXT"
            )
        if "remember_token_expires_at" not in cols:
            self.conn.execute(
                "ALTER TABLE users ADD COLUMN remember_token_expires_at TEXT"
            )
        self.conn.execute(
            "UPDATE users SET remember_token_expires_at=datetime('now', '+30 days') "
            "WHERE remember_token IS NOT NULL "
            "AND (remember_token_expires_at IS NULL OR remember_token_expires_at='')"
        )
        self.conn.execute(
            "UPDATE users SET password_changed_at=COALESCE(created_at, datetime('now')) "
            "WHERE password_changed_at IS NULL OR password_changed_at=''"
        )
        self.conn.execute(
            "UPDATE users SET recovery_key_created_at=COALESCE(created_at, datetime('now')) "
            "WHERE recovery_key_hash IS NOT NULL "
            "AND (recovery_key_created_at IS NULL OR recovery_key_created_at='')"
        )
        user_count = int(self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])
        admin_count = int(
            self.conn.execute(
                "SELECT COUNT(*) FROM users WHERE COALESCE(is_admin,0)=1"
            ).fetchone()[0]
        )
        if user_count > 0 and admin_count == 0:
            self.conn.execute(
                "UPDATE users SET is_admin=1 "
                "WHERE id=(SELECT id FROM users ORDER BY id LIMIT 1)"
            )

    def _table_exists(self, name: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        return row is not None

    def _columns(self, table: str) -> set[str]:
        table_sql = self._quote_identifier(table)
        if not self._table_exists(table):
            return set()
        return {row[1] for row in self.conn.execute(f"PRAGMA table_info({table_sql})")}

    def _row_count(self, table: str) -> int:
        table_sql = self._quote_identifier(table)
        if not self._table_exists(table):
            return 0
        return int(self.conn.execute(f"SELECT COUNT(*) FROM {table_sql}").fetchone()[0])

    def _legacy_data_exists(self) -> bool:
        worklog_legacy = any(
            self._table_exists(table) and "user_id" not in self._columns(table)
            and self._row_count(table) > 0
            for table in _WORKLOG_TABLE_NAMES
        )
        return any(
            self._row_count(table) > 0
            for table in (
                "worklog",
                "settings",
                "quick_logs",
                "calendar_events",
                "reports",
            )
            if self._table_exists(table) and "user_id" not in self._columns(table)
        ) or worklog_legacy

    def _first_user_id_unlocked(self) -> int | None:
        if not self._table_exists("users"):
            return None
        row = self.conn.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
        return int(row[0]) if row else None

    @staticmethod
    def _quote_identifier(name: str) -> str:
        if (
            not isinstance(name, str)
            or not name
            or not (name[0].isalpha() or name[0] == "_")
            or any(not (ch.isalnum() or ch == "_") for ch in name)
        ):
            raise ValueError(f"invalid_sql_identifier:{name}")
        return f'"{name}"'

    @classmethod
    def _col_expr(cls, cols: set[str], name: str, default_sql: str) -> str:
        return cls._quote_identifier(name) if name in cols else default_sql

    def _legacy_name(self, table: str) -> str:
        self._quote_identifier(table)
        return f"{table}_legacy_{int(time.time() * 1000)}"

    def _migrate_worklog_table(self, fallback_user_id: int | None) -> None:
        for variant in _WORKLOG_TABLE_NAMES[1:]:
            if not self._table_exists("worklog") and self._table_exists(variant):
                self.conn.execute(
                    f"ALTER TABLE {self._quote_identifier(variant)} "
                    f"RENAME TO {self._quote_identifier('worklog')}"
                )
                break
        if not self._table_exists("worklog"):
            self.conn.execute(_CREATE_WORKLOG)
            return
        cols = self._columns("worklog")
        if "user_id" in cols:
            self.conn.execute(_CREATE_WORKLOG)
            return

        legacy = self._legacy_name("worklog")
        legacy_sql = self._quote_identifier(legacy)
        self.conn.execute(
            f"ALTER TABLE {self._quote_identifier('worklog')} RENAME TO {legacy_sql}"
        )
        self.conn.execute(_CREATE_WORKLOG)
        legacy_cols = self._columns(legacy)
        if fallback_user_id is not None and "d" in legacy_cols:
            break_expr = (
                '"break"' if "break" in legacy_cols
                else '"lunch"' if "lunch" in legacy_cols
                else "0"
            )
            start_expr = self._col_expr(legacy_cols, "start", "NULL")
            end_expr = self._col_expr(legacy_cols, "end", "NULL")
            note_expr = self._col_expr(legacy_cols, "note", "''")
            work_type_expr = self._col_expr(legacy_cols, "work_type", "'normal'")
            overnight_expr = self._col_expr(legacy_cols, "overnight", "0")
            self.conn.execute(
                "INSERT OR REPLACE INTO worklog"
                "(user_id,d,start,end,break,note,work_type,overnight) "
                f"SELECT ?, d, {start_expr}, {end_expr}, {break_expr}, "
                f"{note_expr}, {work_type_expr}, {overnight_expr} FROM {legacy_sql}",
                (fallback_user_id,),
            )
        self.conn.execute(f"DROP TABLE {legacy_sql}")

    def _migrate_settings_table(self, fallback_user_id: int | None) -> None:
        if not self._table_exists("settings"):
            self.conn.execute(_CREATE_SETTINGS)
            return
        cols = self._columns("settings")
        if "user_id" in cols:
            self.conn.execute(_CREATE_SETTINGS)
            return

        legacy = self._legacy_name("settings")
        legacy_sql = self._quote_identifier(legacy)
        self.conn.execute(
            f"ALTER TABLE {self._quote_identifier('settings')} RENAME TO {legacy_sql}"
        )
        self.conn.execute(_CREATE_SETTINGS)
        legacy_cols = self._columns(legacy)
        if fallback_user_id is not None and "key" in legacy_cols:
            value_expr = self._col_expr(legacy_cols, "value", "''")
            self.conn.execute(
                "INSERT OR REPLACE INTO settings(user_id,key,value) "
                f"SELECT ?, key, {value_expr} FROM {legacy_sql}",
                (fallback_user_id,),
            )
        self.conn.execute(f"DROP TABLE {legacy_sql}")

    def _migrate_quick_logs_table(self, fallback_user_id: int | None) -> None:
        if not self._table_exists("quick_logs"):
            self.conn.execute(_CREATE_QUICK_LOGS)
            return
        cols = self._columns("quick_logs")
        if "user_id" in cols:
            self.conn.execute(_CREATE_QUICK_LOGS)
            return

        legacy = self._legacy_name("quick_logs")
        legacy_sql = self._quote_identifier(legacy)
        self.conn.execute(
            f"ALTER TABLE {self._quote_identifier('quick_logs')} RENAME TO {legacy_sql}"
        )
        self.conn.execute(_CREATE_QUICK_LOGS)
        legacy_cols = self._columns(legacy)
        if fallback_user_id is not None and {"date", "time", "description"} <= legacy_cols:
            end_expr = self._col_expr(legacy_cols, "end_time", "''")
            created_expr = self._col_expr(legacy_cols, "created_at", "datetime('now')")
            id_expr = self._col_expr(legacy_cols, "id", "NULL")
            self.conn.execute(
                "INSERT INTO quick_logs"
                "(id,user_id,date,time,end_time,description,created_at) "
                f"SELECT {id_expr}, ?, date, time, {end_expr}, description, "
                f"{created_expr} FROM {legacy_sql}",
                (fallback_user_id,),
            )
        self.conn.execute(f"DROP TABLE {legacy_sql}")

    def _migrate_calendar_table(self, fallback_user_id: int | None) -> None:
        if not self._table_exists("calendar_events"):
            self.conn.execute(_CREATE_CALENDAR)
            return
        cols = self._columns("calendar_events")
        if "user_id" in cols:
            self.conn.execute(_CREATE_CALENDAR)
            return

        legacy = self._legacy_name("calendar_events")
        legacy_sql = self._quote_identifier(legacy)
        self.conn.execute(
            f"ALTER TABLE {self._quote_identifier('calendar_events')} "
            f"RENAME TO {legacy_sql}"
        )
        self.conn.execute(_CREATE_CALENDAR)
        legacy_cols = self._columns(legacy)
        if fallback_user_id is not None and {"date", "summary"} <= legacy_cols:
            id_expr = self._col_expr(legacy_cols, "id", "NULL")
            start_expr = self._col_expr(legacy_cols, "start_time", "NULL")
            end_expr = self._col_expr(legacy_cols, "end_time", "NULL")
            description_expr = self._col_expr(legacy_cols, "description", "''")
            location_expr = self._col_expr(legacy_cols, "location", "''")
            all_day_expr = self._col_expr(legacy_cols, "all_day", "0")
            source_expr = self._col_expr(legacy_cols, "source_file", "''")
            self.conn.execute(
                "INSERT INTO calendar_events"
                "(id,user_id,date,start_time,end_time,summary,description,location,all_day,source_file) "
                f"SELECT {id_expr}, ?, date, {start_expr}, {end_expr}, summary, "
                f"{description_expr}, {location_expr}, {all_day_expr}, {source_expr} "
                f"FROM {legacy_sql}",
                (fallback_user_id,),
            )
        self.conn.execute(f"DROP TABLE {legacy_sql}")

    def _migrate_reports_table(self, fallback_user_id: int | None) -> None:
        if not self._table_exists("reports"):
            self.conn.execute(_CREATE_REPORTS)
            return
        cols = self._columns("reports")
        if "user_id" in cols:
            self.conn.execute(_CREATE_REPORTS)
            return

        legacy = self._legacy_name("reports")
        legacy_sql = self._quote_identifier(legacy)
        self.conn.execute(
            f"ALTER TABLE {self._quote_identifier('reports')} RENAME TO {legacy_sql}"
        )
        self.conn.execute(_CREATE_REPORTS)
        legacy_cols = self._columns(legacy)
        required = {"type", "period_start", "period_end", "content"}
        if fallback_user_id is not None and required <= legacy_cols:
            id_expr = self._col_expr(legacy_cols, "id", "NULL")
            created_expr = self._col_expr(legacy_cols, "created_at", "datetime('now')")
            self.conn.execute(
                "INSERT INTO reports"
                "(id,user_id,type,period_start,period_end,content,created_at) "
                f"SELECT {id_expr}, ?, type, period_start, period_end, content, "
                f"{created_expr} FROM {legacy_sql}",
                (fallback_user_id,),
            )
        self.conn.execute(f"DROP TABLE {legacy_sql}")

    @staticmethod
    def _password_hash_with_iterations(
        password: str,
        salt_hex: str,
        iterations: int,
    ) -> str:
        salt = bytes.fromhex(salt_hex)
        return hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations,
        ).hex()

    @classmethod
    def _password_hash(cls, password: str, salt_hex: str) -> str:
        return cls._password_hash_with_iterations(
            password,
            salt_hex,
            _PBKDF2_ITERATIONS,
        )

    @classmethod
    def _password_hash_matches(
        cls,
        password: str,
        salt_hex: str,
        stored_hash: str,
    ) -> tuple[bool, bool]:
        current = cls._password_hash(password, salt_hex)
        if hmac.compare_digest(current, stored_hash):
            return True, False
        for iterations in _PBKDF2_LEGACY_ITERATIONS:
            legacy = cls._password_hash_with_iterations(
                password,
                salt_hex,
                iterations,
            )
            if hmac.compare_digest(legacy, stored_hash):
                return True, True
        return False, False

    def _upgrade_password_hash(
        self,
        user_id: int,
        password: str,
        old_hash: str,
        old_salt: str,
    ) -> None:
        salt = secrets.token_hex(16)
        password_hash = self._password_hash(password, salt)
        with self._write_lock:
            self.conn.execute(
                "UPDATE users SET password_hash=?, salt=? "
                "WHERE id=? AND password_hash=? AND salt=?",
                (password_hash, salt, user_id, old_hash, old_salt),
            )
            self.conn.commit()

    def _upgrade_recovery_key_hash(
        self,
        user_id: int,
        recovery_key: str,
        old_hash: str,
        old_salt: str,
    ) -> None:
        salt = secrets.token_hex(16)
        key_hash = self._password_hash(recovery_key, salt)
        with self._write_lock:
            self.conn.execute(
                "UPDATE users SET recovery_key_hash=?, recovery_salt=? "
                "WHERE id=? AND recovery_key_hash=? AND recovery_salt=?",
                (key_hash, salt, user_id, old_hash, old_salt),
            )
            self.conn.commit()

    @staticmethod
    def _clean_username(username: str) -> str:
        if not isinstance(username, str):
            raise TypeError("username_must_be_string")
        username = username.strip()
        if not username:
            raise ValueError("username_required")
        return username

    def _create_user_unlocked(
        self,
        username: str,
        password: str,
        *,
        recovery_key: str | None = None,
        is_admin: bool = False,
    ) -> int:
        username = self._clean_username(username)
        if not password:
            raise ValueError("password_required")
        salt = secrets.token_hex(16)
        password_hash = self._password_hash(password, salt)
        recovery_salt = secrets.token_hex(16) if recovery_key else None
        recovery_key_hash = (
            self._password_hash(recovery_key, recovery_salt)
            if recovery_key and recovery_salt else None
        )
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = self.conn.execute(
            "INSERT INTO users"
            "(username,password_hash,salt,recovery_key_hash,recovery_salt,is_admin,"
            "created_at,password_changed_at,recovery_key_created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (
                username,
                password_hash,
                salt,
                recovery_key_hash,
                recovery_salt,
                1 if is_admin else 0,
                now,
                now,
                now if recovery_key_hash else None,
            ),
        )
        return int(cur.lastrowid)

    def create_user(
        self,
        username: str,
        password: str,
        *,
        recovery_key: str | None = None,
        is_admin: bool = False,
    ) -> int:
        with self._write_lock:
            user_id = self._create_user_unlocked(
                username,
                password,
                recovery_key=recovery_key,
                is_admin=is_admin,
            )
            self.conn.commit()
            return user_id

    def verify_user(self, username: str, password: str) -> int | None:
        try:
            username = self._clean_username(username)
        except (TypeError, ValueError):
            return None
        row = self.conn.execute(
            "SELECT id,password_hash,salt FROM users WHERE username=?",
            (username,),
        ).fetchone()
        if not row:
            return None
        matched, needs_upgrade = self._password_hash_matches(
            password,
            row[2],
            row[1],
        )
        if not matched:
            return None
        user_id = int(row[0])
        if needs_upgrade:
            self._upgrade_password_hash(user_id, password, row[1], row[2])
        return user_id

    def verify_user_id(self, user_id: int, password: str) -> bool:
        row = self.conn.execute(
            "SELECT password_hash,salt FROM users WHERE id=?",
            (user_id,),
        ).fetchone()
        if not row:
            return False
        matched, needs_upgrade = self._password_hash_matches(
            password,
            row[1],
            row[0],
        )
        if matched and needs_upgrade:
            self._upgrade_password_hash(user_id, password, row[0], row[1])
        return matched

    def verify_recovery_key(self, username: str, recovery_key: str) -> int | None:
        try:
            username = self._clean_username(username)
        except (TypeError, ValueError):
            return None
        row = self.conn.execute(
            "SELECT id,recovery_key_hash,recovery_salt FROM users WHERE username=?",
            (username,),
        ).fetchone()
        if not row or not row[1] or not row[2]:
            return None
        cleaned_key = recovery_key.strip()
        matched, needs_upgrade = self._password_hash_matches(
            cleaned_key,
            row[2],
            row[1],
        )
        if not matched:
            return None
        user_id = int(row[0])
        if needs_upgrade:
            self._upgrade_recovery_key_hash(user_id, cleaned_key, row[1], row[2])
        return user_id

    def regenerate_recovery_key(self, username: str) -> str:
        username = self._clean_username(username)
        if self.get_user_by_username(username) is None:
            raise ValueError("user_not_found")
        recovery_key = secrets.token_hex(16)
        recovery_salt = secrets.token_hex(16)
        recovery_key_hash = self._password_hash(recovery_key, recovery_salt)
        with self._write_lock:
            self.conn.execute(
                "UPDATE users SET recovery_key_hash=?, recovery_salt=?, "
                "recovery_key_created_at=? WHERE username=?",
                (
                    recovery_key_hash,
                    recovery_salt,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    username,
                ),
            )
            self.conn.commit()
        return recovery_key

    def change_password(self, user_id: int, old_pw: str, new_pw: str) -> bool:
        row = self.conn.execute(
            "SELECT password_hash,salt FROM users WHERE id=?",
            (user_id,),
        ).fetchone()
        if not row:
            return False
        matched, _needs_upgrade = self._password_hash_matches(old_pw, row[1], row[0])
        if not matched:
            return False
        salt = secrets.token_hex(16)
        password_hash = self._password_hash(new_pw, salt)
        with self._write_lock:
            self.conn.execute(
                "UPDATE users SET password_hash=?, salt=?, remember_token=NULL, "
                "remember_token_expires_at=NULL, password_changed_at=datetime('now') "
                "WHERE id=?",
                (password_hash, salt, user_id),
            )
            self.conn.commit()
        return True

    def reset_password(self, user_id: int, new_pw: str) -> bool:
        if not self.get_user(user_id):
            return False
        salt = secrets.token_hex(16)
        password_hash = self._password_hash(new_pw, salt)
        with self._write_lock:
            self.conn.execute(
                "UPDATE users SET password_hash=?, salt=?, remember_token=NULL, "
                "remember_token_expires_at=NULL, password_changed_at=datetime('now') "
                "WHERE id=?",
                (password_hash, salt, user_id),
            )
            self.conn.commit()
        return True

    def is_admin(self, user_id: int) -> bool:
        row = self.conn.execute(
            "SELECT COALESCE(is_admin,0) FROM users WHERE id=?",
            (user_id,),
        ).fetchone()
        return bool(row and int(row[0]) == 1)

    def admin_count(self) -> int:
        return int(
            self.conn.execute(
                "SELECT COUNT(*) FROM users WHERE COALESCE(is_admin,0)=1"
            ).fetchone()[0]
        )

    def set_admin(self, user_id: int, enabled: bool) -> bool:
        if not self.get_user(user_id):
            return False
        with self._write_lock:
            self.conn.execute(
                "UPDATE users SET is_admin=? WHERE id=?",
                (1 if enabled else 0, user_id),
            )
            self.conn.commit()
        return True

    def set_remember_token(self, user_id: int, token: str | None) -> None:
        expires_at = None
        if token:
            expires_at = (
                datetime.now() + timedelta(days=REMEMBER_TOKEN_LIFETIME_DAYS)
            ).isoformat(timespec="seconds")
        with self._write_lock:
            self.conn.execute(
                "UPDATE users SET remember_token=?, remember_token_expires_at=? "
                "WHERE id=?",
                (token or None, expires_at, user_id),
            )
            self.conn.commit()

    def get_user_by_token(self, token: str) -> dict | None:
        if not token:
            return None
        row = self.conn.execute(
            "SELECT id,username,created_at,password_changed_at,is_admin,"
            "recovery_key_hash,recovery_key_created_at,remember_token_expires_at "
            "FROM users WHERE remember_token=?",
            (token,),
        ).fetchone()
        if row and self._remember_token_is_expired(row[7]):
            self.set_remember_token(int(row[0]), None)
            return None
        return self._user_row(row) if row else None

    @staticmethod
    def _remember_token_is_expired(raw_expires_at) -> bool:
        if not raw_expires_at:
            return True
        try:
            expires_at = datetime.fromisoformat(str(raw_expires_at))
        except ValueError:
            return True
        return datetime.now() >= expires_at

    def get_user_by_username(self, username: str) -> dict | None:
        try:
            username = self._clean_username(username)
        except (TypeError, ValueError):
            return None
        row = self.conn.execute(
            "SELECT id,username,created_at,password_changed_at,is_admin,"
            "recovery_key_hash,recovery_key_created_at "
            "FROM users WHERE username=?",
            (username,),
        ).fetchone()
        return self._user_row(row) if row else None

    def get_user(self, user_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT id,username,created_at,password_changed_at,is_admin,"
            "recovery_key_hash,recovery_key_created_at "
            "FROM users WHERE id=?",
            (user_id,),
        ).fetchone()
        return self._user_row(row) if row else None

    def first_user(self) -> dict | None:
        row = self.conn.execute(
            "SELECT id,username,created_at,password_changed_at,is_admin,"
            "recovery_key_hash,recovery_key_created_at "
            "FROM users ORDER BY id LIMIT 1"
        ).fetchone()
        return self._user_row(row) if row else None

    def user_count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def list_users(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id,username,created_at,password_changed_at,is_admin,"
            "recovery_key_hash,recovery_key_created_at "
            "FROM users ORDER BY username COLLATE NOCASE"
        ).fetchall()
        return [self._user_row(row) for row in rows]

    @staticmethod
    def _user_row(row) -> dict:
        password_changed_at = row[3] if len(row) > 3 else row[2]
        is_admin = bool(row[4]) if len(row) > 4 else False
        has_recovery_key = bool(row[5]) if len(row) > 5 else False
        recovery_key_created_at = row[6] if len(row) > 6 else ""
        return dict(
            id=int(row[0]),
            username=row[1],
            created_at=row[2],
            password_changed_at=password_changed_at,
            is_admin=is_admin,
            has_recovery_key=has_recovery_key,
            recovery_key_created_at=recovery_key_created_at,
        )

    @staticmethod
    def _report_row(row) -> dict:
        return {
            "id": int(row[0]),
            "type": row[1],
            "period_start": row[2],
            "period_end": row[3],
            "content": row[4],
            "created_at": row[5],
        }

    # Read operations.

    def get(self, d: str, *, user_id: int) -> WorkRecord | None:
        c = self.conn.cursor()
        c.execute(
            "SELECT d,start,end,break,note,work_type,overnight "
            "FROM worklog WHERE user_id=? AND d=?",
            (user_id, d),
        )
        row = c.fetchone()
        return WorkRecord(*row) if row else None

    def month(self, ym: str, *, user_id: int) -> list[WorkRecord]:
        c = self.conn.cursor()
        c.execute(
            "SELECT d,start,end,break,note,work_type,overnight "
            "FROM worklog WHERE user_id=? AND d LIKE ? ORDER BY d",
            (user_id, ym + "%"),
        )
        return [WorkRecord(*r) for r in c.fetchall()]

    def all_records(self, *, user_id: int) -> list[WorkRecord]:
        c = self.conn.cursor()
        c.execute(
            "SELECT d,start,end,break,note,work_type,overnight "
            "FROM worklog WHERE user_id=? ORDER BY d",
            (user_id,),
        )
        return [WorkRecord(*r) for r in c.fetchall()]

    def get_data_date_range(self, *, user_id: int) -> tuple[date | None, date | None]:
        row = self.conn.execute(
            "SELECT MIN(d), MAX(d) FROM worklog WHERE user_id=? AND d IS NOT NULL AND d<>''",
            (user_id,),
        ).fetchone()
        if not row or row[0] is None or row[1] is None:
            return None, None

        def _parse(raw) -> date | None:
            try:
                return date.fromisoformat(str(raw))
            except (TypeError, ValueError):
                return None

        return _parse(row[0]), _parse(row[1])

    def get_setting(self, key: str, default=None, *, user_id: int):
        c = self.conn.cursor()
        c.execute(
            "SELECT value FROM settings WHERE user_id=? AND key=?",
            (user_id, key),
        )
        row = c.fetchone()
        return row[0] if row else default

    # Write operations.

    def save(
        self,
        d,
        s,
        e,
        l,
        n,
        wt="normal",
        overnight: int | None = None,
        *,
        user_id: int,
    ) -> None:
        ovn = int(overnight) if overnight is not None else (
            1 if (s and e and is_overnight_shift(s, e)) else 0
        )
        with self._write_lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO worklog"
                "(user_id,d,start,end,break,note,work_type,overnight) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (user_id, d, s, e, l, n, wt or "normal", ovn),
            )
            self.conn.commit()

    def set_setting(self, key: str, value, *, user_id: int) -> None:
        with self._write_lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO settings(user_id,key,value) VALUES(?,?,?)",
                (user_id, key, str(value)),
            )
            self.conn.commit()

    def save_report(
        self,
        report_type: str,
        period_start: str,
        period_end: str,
        content: str,
        *,
        user_id: int,
    ) -> int:
        with self._write_lock:
            existing = self.conn.execute(
                "SELECT id FROM reports "
                "WHERE user_id=? AND type=? AND period_start=? AND period_end=? "
                "ORDER BY id DESC LIMIT 1",
                (user_id, report_type, period_start, period_end),
            ).fetchone()
            if existing:
                report_id = int(existing[0])
                self.conn.execute(
                    "UPDATE reports SET content=?, created_at=datetime('now') "
                    "WHERE id=? AND user_id=?",
                    (content, report_id, user_id),
                )
                self.conn.commit()
                return report_id
            cur = self.conn.execute(
                "INSERT INTO reports"
                "(user_id,type,period_start,period_end,content,created_at) "
                "VALUES(?,?,?,?,?,datetime('now'))",
                (user_id, report_type, period_start, period_end, content),
            )
            self.conn.commit()
            return int(cur.lastrowid)

    def get_report_for_period(
        self,
        report_type: str,
        period_start: str,
        period_end: str,
        *,
        user_id: int,
    ) -> dict | None:
        row = self.conn.execute(
            "SELECT id,type,period_start,period_end,content,created_at "
            "FROM reports "
            "WHERE user_id=? AND type=? AND period_start=? AND period_end=? "
            "ORDER BY id DESC LIMIT 1",
            (user_id, report_type, period_start, period_end),
        ).fetchone()
        return self._report_row(row) if row else None

    def get_reports_by_type(self, report_type: str, *, user_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id,type,period_start,period_end,content,created_at "
            "FROM reports WHERE user_id=? AND type=? "
            "ORDER BY created_at DESC, id DESC",
            (user_id, report_type),
        ).fetchall()
        return [self._report_row(row) for row in rows]

    def delete_report(self, report_id: int, *, user_id: int) -> None:
        with self._write_lock:
            self.conn.execute(
                "DELETE FROM reports WHERE id=? AND user_id=?",
                (report_id, user_id),
            )
            self.conn.commit()

    def save_calendar_events(self, events: list, source_file: str = "", *, user_id: int) -> int:
        count = 0
        with self._write_lock:
            for ev in events:
                d = ev.get("date")
                summary = ev.get("summary", "")
                if not d or not summary:
                    continue
                d_str = d.isoformat() if hasattr(d, "isoformat") else str(d)
                start = ev.get("start")
                end_ev = ev.get("end")
                start_s = start.strftime("%H:%M") if start and hasattr(
                    start, "strftime") else ""
                end_s = end_ev.strftime("%H:%M") if end_ev and hasattr(
                    end_ev, "strftime") else ""
                self.conn.execute(
                    "INSERT INTO calendar_events "
                    "(user_id,date,start_time,end_time,summary,description,location,all_day,source_file) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (user_id, d_str, start_s, end_s, summary,
                     ev.get("description", ""), ev.get("location", ""),
                     1 if ev.get("all_day") else 0, source_file),
                )
                count += 1
            self.conn.commit()
        return count

    def clear_calendar_events(self, *, user_id: int) -> None:
        with self._write_lock:
            self.conn.execute("DELETE FROM calendar_events WHERE user_id=?", (user_id,))
            self.conn.commit()

    def add_quick_log(self, date_str: str, time_str: str,
                      description: str, end_time: str = "", *, user_id: int) -> int:
        from datetime import datetime as _dt
        with self._write_lock:
            cur = self.conn.execute(
                "INSERT INTO quick_logs (user_id, date, time, end_time, description, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (user_id, date_str, time_str, end_time, description,
                 _dt.now().strftime("%Y-%m-%dT%H:%M:%S")),
            )
            self.conn.commit()
            return int(cur.lastrowid)

    def update_quick_log(self, log_id: int, description: str,
                         time_str: str = "", end_time: str = "", *, user_id: int) -> None:
        with self._write_lock:
            if time_str:
                self.conn.execute(
                    "UPDATE quick_logs SET description=?, time=?, end_time=? "
                    "WHERE id=? AND user_id=?",
                    (description, time_str, end_time, log_id, user_id),
                )
            else:
                self.conn.execute(
                    "UPDATE quick_logs SET description=?, end_time=? "
                    "WHERE id=? AND user_id=?",
                    (description, end_time, log_id, user_id),
                )
            self.conn.commit()

    def delete_quick_log(self, log_id: int, *, user_id: int) -> None:
        with self._write_lock:
            self.conn.execute(
                "DELETE FROM quick_logs WHERE id=? AND user_id=?",
                (log_id, user_id),
            )
            self.conn.commit()

    # Read-only calendar and quick-log queries.

    def get_calendar_events_for_date(self, d: str, *, user_id: int) -> list:
        c = self.conn.cursor()
        c.execute(
            "SELECT id,date,start_time,end_time,summary,description,location,all_day "
            "FROM calendar_events WHERE user_id=? AND date=? ORDER BY start_time",
            (user_id, d),
        )
        return [self._cal_row(r) for r in c.fetchall()]

    def get_calendar_events_for_range(self, start_d: str, end_d: str, *, user_id: int) -> list:
        c = self.conn.cursor()
        c.execute(
            "SELECT id,date,start_time,end_time,summary,description,location,all_day "
            "FROM calendar_events WHERE user_id=? AND date BETWEEN ? AND ? "
            "ORDER BY date,start_time",
            (user_id, start_d, end_d),
        )
        return [self._cal_row(r) for r in c.fetchall()]

    @staticmethod
    def _cal_row(r) -> dict:
        return dict(
            id=r[0], date=r[1], start_time=r[2], end_time=r[3],
            summary=r[4], description=r[5], location=r[6], all_day=bool(r[7]),
        )

    def get_quick_logs_for_date(self, date_str: str, *, user_id: int) -> list[dict]:
        c = self.conn.cursor()
        c.execute(
            "SELECT id, date, time, end_time, description, created_at "
            "FROM quick_logs WHERE user_id=? AND date=? ORDER BY time, created_at",
            (user_id, date_str),
        )
        return [self._ql_row(r) for r in c.fetchall()]

    def get_quick_logs_for_range(self, start_d: str, end_d: str, *, user_id: int) -> list[dict]:
        c = self.conn.cursor()
        c.execute(
            "SELECT id, date, time, end_time, description, created_at "
            "FROM quick_logs WHERE user_id=? AND date BETWEEN ? AND ? ORDER BY date, time",
            (user_id, start_d, end_d),
        )
        return [self._ql_row(r) for r in c.fetchall()]

    @staticmethod
    def _ql_row(r) -> dict:
        return dict(id=r[0], date=r[1], time=r[2], end_time=r[3],
                    description=r[4], created_at=r[5])
