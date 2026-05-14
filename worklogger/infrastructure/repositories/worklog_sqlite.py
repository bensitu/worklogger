"""SQLite work log repository."""

from __future__ import annotations

from datetime import date
import sqlite3

from worklogger.domain.worklog.models import WorkLog
from worklogger.domain.worklog.rules import normalize_work_log, normalize_work_type
from worklogger.infrastructure.database.connection import SQLiteConnectionFactory
from worklogger.infrastructure.repositories._mapping import parse_date


class SQLiteWorkLogRepository:
    def __init__(self, connection_factory: SQLiteConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def get_for_day(self, user_id: int, day: date) -> WorkLog | None:
        with self._connection_factory.connection() as connection:
            row = connection.execute(
                """
                SELECT user_id, d, start, end, "break", note, work_type, overnight
                FROM worklog
                WHERE user_id=? AND d=?
                """,
                (user_id, day.isoformat()),
            ).fetchone()
        return self._from_row(row) if row else None

    def list_for_month(self, user_id: int, year: int, month: int) -> tuple[WorkLog, ...]:
        prefix = f"{int(year):04d}-{int(month):02d}"
        with self._connection_factory.connection() as connection:
            rows = connection.execute(
                """
                SELECT user_id, d, start, end, "break", note, work_type, overnight
                FROM worklog
                WHERE user_id=? AND d BETWEEN ? AND ?
                ORDER BY d
                """,
                (user_id, f"{prefix}-01", f"{prefix}-31"),
            ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def list_all(self, user_id: int) -> tuple[WorkLog, ...]:
        with self._connection_factory.connection() as connection:
            rows = connection.execute(
                """
                SELECT user_id, d, start, end, "break", note, work_type, overnight
                FROM worklog
                WHERE user_id=?
                ORDER BY d
                """,
                (user_id,),
            ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def save(self, work_log: WorkLog) -> None:
        normalized = normalize_work_log(work_log)
        with self._connection_factory.transaction(write=True) as connection:
            connection.execute(
                """
                INSERT INTO worklog(user_id, d, start, end, "break", note, work_type, overnight)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, d) DO UPDATE SET
                    start=excluded.start,
                    end=excluded.end,
                    "break"=excluded."break",
                    note=excluded.note,
                    work_type=excluded.work_type,
                    overnight=excluded.overnight
                """,
                (
                    normalized.user_id,
                    normalized.day.isoformat(),
                    normalized.start_time,
                    normalized.end_time,
                    normalized.break_hours,
                    normalized.note,
                    normalized.work_type.value,
                    1 if normalized.overnight else 0,
                ),
            )

    def remove(self, user_id: int, day: date) -> None:
        with self._connection_factory.transaction(write=True) as connection:
            connection.execute(
                "DELETE FROM worklog WHERE user_id=? AND d=?",
                (user_id, day.isoformat()),
            )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> WorkLog:
        return WorkLog(
            user_id=int(row["user_id"]),
            day=parse_date(row["d"]),
            start_time=row["start"],
            end_time=row["end"],
            break_hours=float(row["break"] or 0),
            note=str(row["note"] or ""),
            work_type=normalize_work_type(row["work_type"]),
            overnight=bool(int(row["overnight"] or 0)),
        )
