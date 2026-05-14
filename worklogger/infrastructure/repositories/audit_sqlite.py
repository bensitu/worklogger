"""SQLite audit event writer."""

from __future__ import annotations

from dataclasses import dataclass
import json

from worklogger.infrastructure.database.connection import SQLiteConnectionFactory
from worklogger.infrastructure.repositories._mapping import utc_now_iso


@dataclass(frozen=True)
class AuditEvent:
    event_type: str
    user_id: int | None = None
    details: dict[str, object] | None = None


class SQLiteAuditRepository:
    def __init__(self, connection_factory: SQLiteConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def record(self, event: AuditEvent) -> None:
        details = json.dumps(event.details or {}, sort_keys=True, ensure_ascii=False)
        with self._connection_factory.transaction(write=True) as connection:
            connection.execute(
                """
                INSERT INTO audit_events(user_id, event_type, details, created_at)
                VALUES(?, ?, ?, ?)
                """,
                (event.user_id, event.event_type, details, utc_now_iso()),
            )
