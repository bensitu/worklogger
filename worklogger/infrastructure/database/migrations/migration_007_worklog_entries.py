"""Preserve daily records as independently editable time entries."""

import sqlite3

from worklogger.infrastructure.database.migrations.snapshot import save_snapshot

VERSION = 7
DESCRIPTION = "worklog_entries"


def prepare(connection_factory) -> None:
    with connection_factory.connection() as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(worklog)")}
        if columns and "id" not in columns and connection.execute("SELECT 1 FROM worklog LIMIT 1").fetchone():
            save_snapshot(connection, connection_factory.database_path, "entries")


def up(connection: sqlite3.Connection) -> None:
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
        SELECT w.user_id,w.d,w.start,w.end,w."break",COALESCE(n.content,w.note),
        w.work_type,w.overnight,w.started_at,w.ended_at FROM worklog w
        LEFT JOIN daily_notes n ON n.user_id=w.user_id AND n.d=w.d''')
    connection.execute("DROP TABLE worklog")
    connection.execute("ALTER TABLE worklog_entries RENAME TO worklog")
    connection.execute("CREATE INDEX worklog_user_date ON worklog(user_id,d,start,id)")
    connection.execute("CREATE UNIQUE INDEX worklog_capture ON worklog(user_id,capture_id) WHERE capture_id IS NOT NULL")
    connection.execute("UPDATE settings SET key='previous_auto_record_state' WHERE key='auto_record_state'")
