"""Preserve daily notes independently from working-hour records."""

import sqlite3

from worklogger.infrastructure.database.migrations.snapshot import save_snapshot

VERSION = 5
DESCRIPTION = "daily_note_storage"


def prepare(connection_factory) -> None:
    with connection_factory.connection() as connection:
        exists = connection.execute("SELECT 1 FROM sqlite_master WHERE name='daily_notes'").fetchone()
        worklog_exists = connection.execute("SELECT 1 FROM sqlite_master WHERE name='worklog'").fetchone()
        if not exists and worklog_exists and connection.execute("SELECT 1 FROM worklog WHERE note<>'' LIMIT 1").fetchone():
            save_snapshot(connection, connection_factory.database_path, "notes")


def up(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS daily_notes("
        "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
        "d TEXT NOT NULL, content TEXT NOT NULL DEFAULT '', PRIMARY KEY(user_id, d))"
    )
    connection.execute(
        "INSERT INTO daily_notes(user_id, d, content) SELECT user_id, d, note FROM worklog WHERE note<>'' "
        "ON CONFLICT(user_id, d) DO NOTHING"
    )
    connection.execute(
        "DELETE FROM worklog WHERE note<>'' AND (start IS NULL OR start='') AND (end IS NULL OR end='') "
        "AND \"break\"=0 AND work_type='normal'"
    )
