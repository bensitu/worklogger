"""Preserve legacy credentials while aligning the authentication columns."""

import sqlite3

from worklogger.infrastructure.database.connection import SQLiteConnectionFactory
from worklogger.infrastructure.database.migrations.snapshot import save_snapshot

VERSION = 2
DESCRIPTION = "legacy_auth_columns"


def prepare(connection_factory: SQLiteConnectionFactory) -> None:
    with connection_factory.connection() as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
        if not columns or {"password_salt", "must_change_password"}.issubset(columns):
            return
        if connection_factory.database_path == ":memory:":
            return
        save_snapshot(connection, connection_factory.database_path, "auth")


def up(connection: sqlite3.Connection) -> None:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
    if "password_salt" not in columns and "salt" not in columns:
        raise ValueError("auth_schema_missing_password_salt")
    connection.execute("SAVEPOINT auth_columns")
    try:
        if "password_salt" not in columns:
            connection.execute("ALTER TABLE users RENAME COLUMN salt TO password_salt")
        if "must_change_password" not in columns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0"
            )
        connection.execute("RELEASE SAVEPOINT auth_columns")
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT auth_columns")
        connection.execute("RELEASE SAVEPOINT auth_columns")
        raise
