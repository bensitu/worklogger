"""SQLite report repository."""

from __future__ import annotations

from datetime import date
import sqlite3

from worklogger.domain.reporting.models import Report
from worklogger.domain.reporting.periods import normalize_report_type
from worklogger.infrastructure.database.connection import SQLiteConnectionFactory
from worklogger.infrastructure.repositories._mapping import (
    parse_date,
    parse_datetime,
    utc_now_iso,
)


class SQLiteReportRepository:
    def __init__(self, connection_factory: SQLiteConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def save(self, report: Report) -> Report:
        report_type = normalize_report_type(report.report_type)
        created_at = report.created_at.isoformat(timespec="seconds") if report.created_at else utc_now_iso()
        with self._connection_factory.transaction(write=True) as connection:
            cursor = connection.execute(
                """
                INSERT INTO reports(user_id, type, period_start, period_end, content, created_at)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    report.user_id,
                    report_type,
                    report.period_start.isoformat(),
                    report.period_end.isoformat(),
                    report.content,
                    created_at,
                ),
            )
            report_id = int(cursor.lastrowid)
        return Report(
            id=report_id,
            user_id=report.user_id,
            report_type=report_type,
            period_start=report.period_start,
            period_end=report.period_end,
            content=report.content,
            created_at=parse_datetime(created_at),
        )

    def get_for_period(
        self,
        user_id: int,
        report_type: str,
        period_start: date,
        period_end: date,
    ) -> Report | None:
        normalized_type = normalize_report_type(report_type)
        with self._connection_factory.connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM reports
                WHERE user_id=? AND type=? AND period_start=? AND period_end=?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (
                    user_id,
                    normalized_type,
                    period_start.isoformat(),
                    period_end.isoformat(),
                ),
            ).fetchone()
        return self._from_row(row) if row else None

    def list_by_type(self, user_id: int, report_type: str) -> tuple[Report, ...]:
        normalized_type = normalize_report_type(report_type)
        with self._connection_factory.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM reports
                WHERE user_id=? AND type=?
                ORDER BY period_start DESC, created_at DESC, id DESC
                """,
                (user_id, normalized_type),
            ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def remove(self, user_id: int, report_id: int) -> None:
        with self._connection_factory.transaction(write=True) as connection:
            connection.execute(
                "DELETE FROM reports WHERE user_id=? AND id=?",
                (user_id, report_id),
            )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Report:
        return Report(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            report_type=str(row["type"]),
            period_start=parse_date(row["period_start"]),
            period_end=parse_date(row["period_end"]),
            content=str(row["content"]),
            created_at=parse_datetime(row["created_at"]),
        )
