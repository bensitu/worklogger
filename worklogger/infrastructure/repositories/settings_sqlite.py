"""SQLite settings repository."""

from __future__ import annotations

from worklogger.infrastructure.database.connection import SQLiteConnectionFactory


class SQLiteSettingsRepository:
    def __init__(self, connection_factory: SQLiteConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def get(self, user_id: int, key: str, default: str | None = None) -> str | None:
        with self._connection_factory.connection() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE user_id=? AND key=?",
                (user_id, key),
            ).fetchone()
        return str(row["value"]) if row else default

    def set(self, user_id: int, key: str, value: str) -> None:
        with self._connection_factory.transaction(write=True) as connection:
            connection.execute(
                """
                INSERT INTO settings(user_id, key, value)
                VALUES(?, ?, ?)
                ON CONFLICT(user_id, key) DO UPDATE SET value=excluded.value
                """,
                (user_id, key, str(value)),
            )

    def delete(self, user_id: int, key: str) -> None:
        with self._connection_factory.transaction(write=True) as connection:
            connection.execute(
                "DELETE FROM settings WHERE user_id=? AND key=?",
                (user_id, key),
            )

    def list_user_ids_for_key_value(self, key: str, value: str) -> tuple[int, ...]:
        with self._connection_factory.connection() as connection:
            rows = connection.execute(
                "SELECT user_id FROM settings WHERE key=? AND value=? ORDER BY user_id",
                (key, str(value)),
            ).fetchall()
        return tuple(int(row["user_id"]) for row in rows)
