"""Retain offset-aware timestamps without reinterpreting existing clock times."""

import sqlite3

from worklogger.infrastructure.database.migrations.snapshot import save_snapshot

VERSION = 6
DESCRIPTION = "worklog_timestamps"


def prepare(connection_factory) -> None:
    with connection_factory.connection() as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(worklog)")}
        if columns and "started_at" not in columns and connection.execute("SELECT 1 FROM worklog LIMIT 1").fetchone():
            save_snapshot(connection, connection_factory.database_path, "timestamps")


def up(connection: sqlite3.Connection) -> None:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(worklog)")}
    for column in ("started_at", "ended_at"):
        if column not in columns:
            connection.execute(f"ALTER TABLE worklog ADD COLUMN {column} TEXT")
