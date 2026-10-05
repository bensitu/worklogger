"""Preserve stored activity records while updating their table name."""

import sqlite3

from worklogger.infrastructure.database.connection import SQLiteConnectionFactory
from worklogger.infrastructure.database.migrations.snapshot import save_snapshot

VERSION = 3
DESCRIPTION = "activity_event_names"
_PREVIOUS_TABLE = "audit_events"
_PREVIOUS_INDEX = "idx_audit_events_user_created"


def prepare(connection_factory: SQLiteConnectionFactory) -> None:
    if connection_factory.database_path == ":memory:":
        return
    with connection_factory.connection() as connection:
        if not _table_exists(connection, _PREVIOUS_TABLE):
            return
        save_snapshot(connection, connection_factory.database_path, "activity")


def up(connection: sqlite3.Connection) -> None:
    # Earlier schema scripts may have committed the runner's transaction.
    if not connection.in_transaction:
        connection.execute("BEGIN IMMEDIATE")
    if _table_exists(connection, _PREVIOUS_TABLE):
        if _table_exists(connection, "activity_events"):
            # Never combine independently populated tables or change record IDs.
            if connection.execute("SELECT 1 FROM activity_events LIMIT 1").fetchone():
                if connection.execute(f'SELECT 1 FROM "{_PREVIOUS_TABLE}" LIMIT 1').fetchone():
                    raise ValueError("activity_event_table_conflict")
                connection.execute(f'DROP TABLE "{_PREVIOUS_TABLE}"')
            else:
                connection.execute("DROP TABLE activity_events")
        if _table_exists(connection, _PREVIOUS_TABLE):
            connection.execute(f'ALTER TABLE "{_PREVIOUS_TABLE}" RENAME TO activity_events')
        connection.execute(f'DROP INDEX IF EXISTS "{_PREVIOUS_INDEX}"')
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_activity_events_user_created "
        "ON activity_events(user_id, created_at)"
    )


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone() is not None
