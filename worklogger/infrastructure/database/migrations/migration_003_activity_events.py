"""Preserve stored activity records while updating their table name."""

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from uuid import uuid4

from worklogger.infrastructure.database.connection import SQLiteConnectionFactory
from worklogger.infrastructure.database.paths import secure_database_files

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
        path = Path(connection_factory.database_path)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = path.with_name(f"{path.name}.bak_activity_{stamp}_{uuid4().hex}")
        with closing(sqlite3.connect(backup)) as destination:
            secure_database_files(backup)
            connection.backup(destination)
            destination.execute("PRAGMA journal_mode=DELETE")
        secure_database_files(backup)


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
