"""Preserve daily notes independently from working-hour records."""

import sqlite3


VERSION = 5
DESCRIPTION = "daily_note_storage"


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
