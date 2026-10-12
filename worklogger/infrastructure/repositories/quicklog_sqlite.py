"""Read-only SQLite access to historical quick log entries."""

from __future__ import annotations

from datetime import date
import sqlite3

from worklogger.domain.quicklog.models import QuickLog
from worklogger.infrastructure.database.connection import SQLiteConnectionFactory
from worklogger.infrastructure.repositories._mapping import (
    parse_date,
    parse_datetime,
    map_rows,
)


class SQLiteQuickLogRepository:
    def __init__(self, connection_factory: SQLiteConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def list_for_day(self, user_id: int, day: date) -> tuple[QuickLog, ...]:
        with self._connection_factory.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM quick_logs
                WHERE user_id=? AND date=?
                ORDER BY time, created_at
                """,
                (user_id, day.isoformat()),
            ).fetchall()
        return map_rows(rows, self._from_row)

    def list_for_range(
        self,
        user_id: int,
        start_day: date,
        end_day: date,
    ) -> tuple[QuickLog, ...]:
        with self._connection_factory.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM quick_logs
                WHERE user_id=? AND date BETWEEN ? AND ?
                ORDER BY date, time, created_at
                """,
                (user_id, start_day.isoformat(), end_day.isoformat()),
            ).fetchall()
        return map_rows(rows, self._from_row)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> QuickLog:
        return QuickLog(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            day=parse_date(row["date"]),
            description=str(row["description"]),
            start_time=str(row["time"] or ""),
            end_time=str(row["end_time"] or ""),
            created_at=parse_datetime(row["created_at"]),
        )
