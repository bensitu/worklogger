"""SQLite activity event writer."""

from __future__ import annotations

from dataclasses import dataclass
import json

from worklogger.infrastructure.database.connection import SQLiteConnectionFactory
from worklogger.infrastructure.repositories._mapping import utc_now_iso


@dataclass(frozen=True)
class ActivityEvent:
    event_type: str
    user_id: int | None = None
    details: dict[str, object] | None = None


class SQLiteActivityRepository:
    def __init__(self, connection_factory: SQLiteConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def record(self, event: ActivityEvent) -> None:
        details = json.dumps(event.details or {}, sort_keys=True, ensure_ascii=False)
        with self._connection_factory.transaction(write=True) as connection:
            connection.execute(
                """
                INSERT INTO activity_events(user_id, event_type, details, created_at)
                VALUES(?, ?, ?, ?)
                """,
                (event.user_id, event.event_type, details, utc_now_iso()),
            )
