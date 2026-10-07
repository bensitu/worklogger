"""Retain offset-aware timestamps without reinterpreting existing clock times."""

import sqlite3


VERSION = 6
DESCRIPTION = "worklog_timestamps"


def up(connection: sqlite3.Connection) -> None:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(worklog)")}
    for column in ("started_at", "ended_at"):
        if column not in columns:
            connection.execute(f"ALTER TABLE worklog ADD COLUMN {column} TEXT")
