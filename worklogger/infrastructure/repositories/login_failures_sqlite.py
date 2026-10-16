"""Persistent login throttling with atomic failure updates."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from worklogger.domain.auth.policies import lockout_until_for_failure_count, username_key
from worklogger.infrastructure.database.connection import SQLiteConnectionFactory
from worklogger.infrastructure.repositories._mapping import parse_datetime

_STALE_ATTEMPTS = "last_failed_at<? OR NOT EXISTS (SELECT 1 FROM users WHERE users.username_key=login_attempts.username)"


class SQLiteLoginFailureRepository:
    def __init__(self, connection_factory: SQLiteConnectionFactory, *, clock: Callable[[], datetime] | None = None) -> None:
        self._connection_factory = connection_factory
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def prune(self) -> None:
        cutoff = (self._clock() - timedelta(days=7)).isoformat()
        with self._connection_factory.connection() as connection:
            if connection.execute("SELECT 1 FROM login_attempts WHERE " + _STALE_ATTEMPTS + " LIMIT 1", (cutoff,)).fetchone() is None:
                return
        with self._connection_factory.transaction(write=True) as connection:
            connection.execute("DELETE FROM login_attempts WHERE " + _STALE_ATTEMPTS, (cutoff,))

    def lockout_until(self, username: str) -> datetime | None:
        try:
            username = username_key(username)
        except (TypeError, ValueError):
            return None
        with self._connection_factory.connection() as connection:
            row = connection.execute(
                "SELECT locked_until FROM login_attempts WHERE username=?",
                (username,),
            ).fetchone()
        locked_until = parse_datetime(row["locked_until"]) if row else None
        if locked_until is None:
            return None
        if locked_until <= self._clock():
            with self._connection_factory.transaction(write=True) as connection:
                connection.execute(
                    "UPDATE login_attempts SET locked_until=NULL WHERE username=?",
                    (username,),
                )
            return None
        return locked_until

    def record_failure(self, username: str) -> tuple[int, datetime | None]:
        username = username_key(username)
        now = self._clock()
        with self._connection_factory.transaction(write=True) as connection:
            column = "username_key"
            if not connection.execute(f"SELECT 1 FROM users WHERE {column}=?", (username,)).fetchone():
                return 0, None
            row = connection.execute(
                "SELECT failed_count, last_failed_at FROM login_attempts WHERE username=?",
                (username,),
            ).fetchone()
            recent = row is not None and (parse_datetime(row["last_failed_at"]) or datetime.min.replace(tzinfo=timezone.utc)) > now - timedelta(hours=24)
            failed_count = min(int(row["failed_count"]) + 1, 20) if recent else 1
            locked_until = lockout_until_for_failure_count(failed_count, now=now)
            locked_until_raw = locked_until.isoformat(timespec="seconds") if locked_until else None
            connection.execute(
                """
                INSERT INTO login_attempts(username, failed_count, locked_until, last_failed_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    failed_count=excluded.failed_count,
                    locked_until=excluded.locked_until,
                    last_failed_at=excluded.last_failed_at
                """,
                (username, failed_count, locked_until_raw, now.isoformat(timespec="seconds")),
            )
        return failed_count, locked_until

    def clear_failures(self, username: str) -> None:
        try:
            username = username_key(username)
        except (TypeError, ValueError):
            return
        with self._connection_factory.transaction(write=True) as connection:
            connection.execute(
                "DELETE FROM login_attempts WHERE username=?",
                (username,),
            )
