"""Preserve daily records as independently editable time entries."""

import sqlite3


VERSION = 7
DESCRIPTION = "worklog_entries"


def up(connection: sqlite3.Connection) -> None:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(worklog)")}
    if "id" in columns:
        if not {"revision", "capture_id"}.issubset(columns):
            raise ValueError("database_schema_unsupported")
        connection.execute("CREATE INDEX IF NOT EXISTS worklog_user_date ON worklog(user_id,d,start,id)")
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS worklog_capture ON worklog(user_id,capture_id) WHERE capture_id IS NOT NULL")
        connection.execute("DROP INDEX IF EXISTS idx_worklog_user_date")
        _convert_timer_key(connection)
        return
    connection.execute('''CREATE TABLE worklog_entries(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        d TEXT NOT NULL, start TEXT, end TEXT,
        "break" REAL NOT NULL DEFAULT 0,
        note TEXT NOT NULL DEFAULT '', work_type TEXT NOT NULL DEFAULT 'normal',
        overnight INTEGER NOT NULL DEFAULT 0, started_at TEXT, ended_at TEXT,
        revision INTEGER NOT NULL DEFAULT 0, capture_id TEXT
    )''')
    connection.execute('''INSERT INTO worklog_entries(user_id,d,start,end,"break",note,work_type,overnight,started_at,ended_at)
        SELECT w.user_id,w.d,w.start,w.end,COALESCE(w."break",0),COALESCE(NULLIF(w.note,''),n.content,''),
        COALESCE(w.work_type,'normal'),COALESCE(w.overnight,0),w.started_at,w.ended_at FROM worklog w
        LEFT JOIN daily_notes n ON n.user_id=w.user_id AND n.d=w.d''')
    connection.execute("DROP TABLE worklog")
    connection.execute("ALTER TABLE worklog_entries RENAME TO worklog")
    connection.execute("CREATE INDEX worklog_user_date ON worklog(user_id,d,start,id)")
    connection.execute("CREATE UNIQUE INDEX worklog_capture ON worklog(user_id,capture_id) WHERE capture_id IS NOT NULL")
    _convert_timer_key(connection)


def _convert_timer_key(connection):
    connection.execute("INSERT INTO settings(user_id,key,value) SELECT user_id,'previous_auto_record_state',value "
                       "FROM settings WHERE key='auto_record_state' AND 1 "
                       "ON CONFLICT(user_id,key) DO NOTHING")
    connection.execute("DELETE FROM settings WHERE key='auto_record_state'")
