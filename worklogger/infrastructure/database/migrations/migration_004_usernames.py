"""Canonical account identifiers and explicit password availability."""

import sqlite3

from worklogger.domain.auth.policies import username_key
from worklogger.infrastructure.database.migrations.snapshot import save_snapshot

VERSION = 4
DESCRIPTION = "canonical_usernames"


def prepare(connection_factory) -> None:
    with connection_factory.connection() as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
        if columns and "username_key" not in columns and connection.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            save_snapshot(connection, connection_factory.database_path, "usernames")


def up(connection: sqlite3.Connection) -> None:
    users = connection.execute("SELECT id, username FROM users").fetchall()
    values = [(username_key(row[1]), row[0]) for row in users]
    if len({value[0] for value in values}) != len(values):
        raise ValueError("username_normalization_conflict")
    columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
    if "username_key" not in columns:
        connection.execute("ALTER TABLE users ADD COLUMN username_key TEXT NOT NULL DEFAULT ''")
    if "local_password_enabled" not in columns:
        connection.execute("ALTER TABLE users ADD COLUMN local_password_enabled INTEGER NOT NULL DEFAULT 1")
        connection.execute(
            "UPDATE users SET local_password_enabled=0 WHERE recovery_key_hash IS NULL "
            "AND EXISTS (SELECT 1 FROM external_identities WHERE external_identities.user_id=users.id)"
        )
    connection.executemany("UPDATE users SET username_key=? WHERE id=?", values)
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_key ON users(username_key)")
    attempts = connection.execute("SELECT username, failed_count, locked_until, last_failed_at FROM login_attempts").fetchall()
    merged = {}
    for name, count, locked_until, last_failed_at in attempts:
        key = username_key(name)
        old = merged.get(key, (0, None, None))
        merged[key] = (min(20, old[0] + count), max(old[1] or "", locked_until or "") or None,
                       max(old[2] or "", last_failed_at or "") or None)
    connection.execute("DELETE FROM login_attempts")
    connection.executemany("INSERT INTO login_attempts VALUES(?, ?, ?, ?)",
                           [(key, *value) for key, value in merged.items()])
