"""SQLite database access layer.

All query methods now return ``WorkRecord`` instances (or lists thereof)
instead of raw tuples, eliminating magic index access throughout the
codebase.

Thread-safety
-------------
``check_same_thread=False`` allows the single connection to be used from
background threads (e.g. CSV import, update checker).  All write operations
are serialised through ``_write_lock`` so concurrent writes never interleave.
"""

import sys
import os
import sqlite3
import shutil
import time
import threading

from config.constants import DB_FILENAME
from core.models import WorkRecord
from core.time_calc import is_overnight_shift


def get_db_path() -> str:
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, DB_FILENAME)


DB_PATH = get_db_path()

_CREATE_WORKLOG = """CREATE TABLE IF NOT EXISTS worklog(
    d TEXT PRIMARY KEY, start TEXT, end TEXT,
    break REAL, note TEXT, work_type TEXT DEFAULT 'normal',
    overnight INTEGER DEFAULT 0)"""

_CREATE_SETTINGS = """CREATE TABLE IF NOT EXISTS settings(
    key TEXT PRIMARY KEY, value TEXT)"""

_CREATE_QUICK_LOGS = """CREATE TABLE IF NOT EXISTS quick_logs(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    time TEXT NOT NULL,
    end_time TEXT DEFAULT '',
    description TEXT NOT NULL,
    created_at TEXT NOT NULL)"""

_CREATE_CALENDAR = """CREATE TABLE IF NOT EXISTS calendar_events(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    start_time TEXT,
    end_time TEXT,
    summary TEXT NOT NULL,
    description TEXT DEFAULT '',
    location TEXT DEFAULT '',
    all_day INTEGER DEFAULT 0,
    source_file TEXT DEFAULT '')"""


class DB:
    def __init__(self):
        # _write_lock serialises all write operations so that background
        # threads (e.g. CSV import, ICS import) sharing this DB instance
        # never interleave commits.
        self._write_lock = threading.Lock()
        self.conn = self._open_connection()
        self._migrate()

    @staticmethod
    def _open_connection() -> sqlite3.Connection:
        # check_same_thread=False: the same connection may be used from
        # background threads; _write_lock in every write method keeps it safe.
        try:
            conn = sqlite3.connect(DB_PATH, timeout=5, check_same_thread=False)
            r = conn.execute("PRAGMA integrity_check").fetchone()
            if r and r[0] != "ok":
                raise sqlite3.DatabaseError(f"Integrity check failed: {r[0]}")
            conn.execute(_CREATE_WORKLOG)
            conn.execute(_CREATE_SETTINGS)
            conn.execute(_CREATE_CALENDAR)
            conn.execute(_CREATE_QUICK_LOGS)
            conn.commit()
            return conn
        except sqlite3.DatabaseError as exc:
            backup = DB_PATH + f".bak_{int(time.time())}"
            try:
                if os.path.exists(DB_PATH):
                    shutil.move(DB_PATH, backup)
            except Exception:
                pass
            try:
                conn = sqlite3.connect(DB_PATH, timeout=5, check_same_thread=False)
                conn.execute(_CREATE_WORKLOG)
                conn.execute(_CREATE_SETTINGS)
                conn.execute(_CREATE_CALENDAR)
                conn.execute(_CREATE_QUICK_LOGS)
                conn.commit()
                return conn
            except sqlite3.DatabaseError:
                raise sqlite3.DatabaseError(
                    f"Cannot recover database at {DB_PATH} after error: {exc}"
                ) from exc

    def _migrate(self):
        """Add columns / tables to existing databases."""
        try:
            cols = [row[1] for row in self.conn.execute(
                "PRAGMA table_info(worklog)").fetchall()]
            if "lunch" in cols and "break" not in cols:
                self.conn.execute(
                    'ALTER TABLE worklog RENAME COLUMN "lunch" TO "break"')
                self.conn.commit()
        except sqlite3.OperationalError:
            pass
        for sql in [
            "ALTER TABLE worklog ADD COLUMN work_type TEXT DEFAULT 'normal'",
            "ALTER TABLE worklog ADD COLUMN overnight INTEGER DEFAULT 0",
        ]:
            try:
                self.conn.execute(sql)
                self.conn.commit()
            except sqlite3.OperationalError:
                pass
        # Keep older databases compatible with newer optional tables.
        self.conn.execute(_CREATE_CALENDAR)
        self.conn.execute(_CREATE_QUICK_LOGS)
        self.conn.commit()

    # ------------------------------------------------------------------
    # Read operations (no lock needed — SQLite reads are safe concurrent)
    # ------------------------------------------------------------------

    def get(self, d: str) -> WorkRecord | None:
        """Return the worklog record for *d* ("YYYY-MM-DD"), or None."""
        c = self.conn.cursor()
        c.execute(
            "SELECT d,start,end,break,note,work_type,overnight FROM worklog WHERE d=?",
            (d,),
        )
        row = c.fetchone()
        return WorkRecord(*row) if row else None

    def month(self, ym: str) -> list[WorkRecord]:
        """Return all worklog records whose date starts with *ym* ("YYYY-MM")."""
        c = self.conn.cursor()
        c.execute(
            "SELECT d,start,end,break,note,work_type,overnight FROM worklog WHERE d LIKE ?",
            (ym + "%",),
        )
        return [WorkRecord(*r) for r in c.fetchall()]

    def all_records(self) -> list[WorkRecord]:
        c = self.conn.cursor()
        c.execute("SELECT d,start,end,break,note,work_type,overnight FROM worklog ORDER BY d")
        return [WorkRecord(*r) for r in c.fetchall()]

    def get_setting(self, key: str, default=None):
        c = self.conn.cursor()
        c.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = c.fetchone()
        return row[0] if row else default

    # ------------------------------------------------------------------
    # Write operations — all acquire _write_lock
    # ------------------------------------------------------------------

    def save(self, d, s, e, l, n, wt="normal", overnight: int | None = None) -> None:
        ovn = int(overnight) if overnight is not None else (
            1 if (s and e and is_overnight_shift(s, e)) else 0
        )
        with self._write_lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO worklog(d,start,end,break,note,work_type,overnight) "
                "VALUES(?,?,?,?,?,?,?)",
                (d, s, e, l, n, wt or "normal", ovn),
            )
            self.conn.commit()

    def set_setting(self, key: str, value) -> None:
        with self._write_lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
                (key, str(value)),
            )
            self.conn.commit()

    def save_calendar_events(self, events: list, source_file: str = "") -> int:
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
                    "(date,start_time,end_time,summary,description,location,all_day,source_file) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (d_str, start_s, end_s, summary,
                     ev.get("description", ""), ev.get("location", ""),
                     1 if ev.get("all_day") else 0, source_file),
                )
                count += 1
            self.conn.commit()
        return count

    def clear_calendar_events(self) -> None:
        with self._write_lock:
            self.conn.execute("DELETE FROM calendar_events")
            self.conn.commit()

    def add_quick_log(self, date_str: str, time_str: str,
                      description: str, end_time: str = "") -> int:
        from datetime import datetime as _dt
        with self._write_lock:
            cur = self.conn.execute(
                "INSERT INTO quick_logs (date, time, end_time, description, created_at) "
                "VALUES (?,?,?,?,?)",
                (date_str, time_str, end_time, description,
                 _dt.now().strftime("%Y-%m-%dT%H:%M:%S")),
            )
            self.conn.commit()
            return cur.lastrowid

    def update_quick_log(self, log_id: int, description: str,
                         time_str: str = "", end_time: str = "") -> None:
        with self._write_lock:
            if time_str:
                self.conn.execute(
                    "UPDATE quick_logs SET description=?, time=?, end_time=? WHERE id=?",
                    (description, time_str, end_time, log_id),
                )
            else:
                self.conn.execute(
                    "UPDATE quick_logs SET description=?, end_time=? WHERE id=?",
                    (description, end_time, log_id),
                )
            self.conn.commit()

    def delete_quick_log(self, log_id: int) -> None:
        with self._write_lock:
            self.conn.execute("DELETE FROM quick_logs WHERE id=?", (log_id,))
            self.conn.commit()

    # ------------------------------------------------------------------
    # Read-only calendar / quick-log queries
    # ------------------------------------------------------------------

    def get_calendar_events_for_date(self, d: str) -> list:
        c = self.conn.cursor()
        c.execute(
            "SELECT id,date,start_time,end_time,summary,description,location,all_day "
            "FROM calendar_events WHERE date=? ORDER BY start_time",
            (d,),
        )
        return [self._cal_row(r) for r in c.fetchall()]

    def get_calendar_events_for_range(self, start_d: str, end_d: str) -> list:
        c = self.conn.cursor()
        c.execute(
            "SELECT id,date,start_time,end_time,summary,description,location,all_day "
            "FROM calendar_events WHERE date BETWEEN ? AND ? ORDER BY date,start_time",
            (start_d, end_d),
        )
        return [self._cal_row(r) for r in c.fetchall()]

    @staticmethod
    def _cal_row(r) -> dict:
        return dict(
            id=r[0], date=r[1], start_time=r[2], end_time=r[3],
            summary=r[4], description=r[5], location=r[6], all_day=bool(r[7]),
        )

    def get_quick_logs_for_date(self, date_str: str) -> list[dict]:
        c = self.conn.cursor()
        c.execute(
            "SELECT id, date, time, end_time, description, created_at "
            "FROM quick_logs WHERE date=? ORDER BY time, created_at",
            (date_str,),
        )
        return [self._ql_row(r) for r in c.fetchall()]

    def get_quick_logs_for_range(self, start_d: str, end_d: str) -> list[dict]:
        c = self.conn.cursor()
        c.execute(
            "SELECT id, date, time, end_time, description, created_at "
            "FROM quick_logs WHERE date BETWEEN ? AND ? ORDER BY date, time",
            (start_d, end_d),
        )
        return [self._ql_row(r) for r in c.fetchall()]

    @staticmethod
    def _ql_row(r) -> dict:
        return dict(id=r[0], date=r[1], time=r[2], end_time=r[3],
                    description=r[4], created_at=r[5])
