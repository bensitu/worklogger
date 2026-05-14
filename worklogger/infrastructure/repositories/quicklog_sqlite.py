"""SQLite quick log repository."""

from __future__ import annotations

from datetime import date
import sqlite3

from worklogger.domain.quicklog.models import QuickLog
from worklogger.domain.quicklog.rules import normalize_quick_log
from worklogger.infrastructure.database.connection import SQLiteConnectionFactory
from worklogger.infrastructure.repositories._mapping import (
    parse_date,
    parse_datetime,
    utc_now_iso,
)


class SQLiteQuickLogRepository:
    def __init__(self, connection_factory: SQLiteConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def add(self, quick_log: QuickLog) -> QuickLog:
        normalized = normalize_quick_log(quick_log)
        created_at = (
            normalized.created_at.isoformat(timespec="seconds")
            if normalized.created_at
            else utc_now_iso()
        )
        with self._connection_factory.transaction(write=True) as connection:
            cursor = connection.execute(
                """
                INSERT INTO quick_logs(user_id, date, time, end_time, description, created_at)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized.user_id,
                    normalized.day.isoformat(),
                    normalized.start_time,
                    normalized.end_time,
                    normalized.description,
                    created_at,
                ),
            )
            quick_log_id = int(cursor.lastrowid)
        return QuickLog(
            id=quick_log_id,
            user_id=normalized.user_id,
            day=normalized.day,
            description=normalized.description,
            start_time=normalized.start_time,
            end_time=normalized.end_time,
            created_at=parse_datetime(created_at),
        )

    def update(self, quick_log: QuickLog) -> None:
        if quick_log.id is None:
            raise ValueError("quick_log_id_required")
        normalized = normalize_quick_log(quick_log)
        with self._connection_factory.transaction(write=True) as connection:
            connection.execute(
                """
                UPDATE quick_logs
                SET date=?, time=?, end_time=?, description=?
                WHERE user_id=? AND id=?
                """,
                (
                    normalized.day.isoformat(),
                    normalized.start_time,
                    normalized.end_time,
                    normalized.description,
                    normalized.user_id,
                    normalized.id,
                ),
            )

    def remove(self, user_id: int, quick_log_id: int) -> None:
        with self._connection_factory.transaction(write=True) as connection:
            connection.execute(
                "DELETE FROM quick_logs WHERE user_id=? AND id=?",
                (user_id, quick_log_id),
            )

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
        return tuple(self._from_row(row) for row in rows)

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
        return tuple(self._from_row(row) for row in rows)

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
