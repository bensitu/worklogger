"""SQLite report repository."""

from __future__ import annotations

from datetime import date
import sqlite3

from worklogger.domain.reporting.models import Report, ReportRevision
from worklogger.infrastructure.repositories.report_provenance_sqlite import encode_provenance, decode_provenance
from worklogger.domain.reporting.periods import normalize_report_type
from worklogger.infrastructure.database.connection import SQLiteConnectionFactory
from worklogger.infrastructure.repositories._mapping import (
    parse_date,
    parse_datetime,
    utc_now_iso,
    map_rows,
)


class SQLiteReportRepository:
    def __init__(self, connection_factory: SQLiteConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def save(self, report: Report) -> Report:
        report_type = normalize_report_type(report.report_type)
        if not isinstance(report.content, str) or len(report.content.encode("utf-8")) > 1024 * 1024:
            raise ValueError("report_content_too_long")
        provenance = encode_provenance(report.provenance)
        now = utc_now_iso()
        with self._connection_factory.transaction(write=True) as connection:
            if report.id is not None:
                cursor = connection.execute(
                    """
                    UPDATE reports SET content=?,revision=revision+1,updated_at=?,provenance=?
                    WHERE id=? AND user_id=? AND type=? AND period_start=? AND period_end=? AND revision=?
                    """,
                    (report.content, now, provenance, report.id, report.user_id, report_type,
                     report.period_start.isoformat(), report.period_end.isoformat(), report.revision),
                )
                if cursor.rowcount != 1:
                    existing = connection.execute("SELECT type,period_start,period_end FROM reports WHERE id=? AND user_id=?", (report.id, report.user_id)).fetchone()
                    if existing and tuple(existing) == (report_type, report.period_start.isoformat(), report.period_end.isoformat()):
                        raise ValueError("report_conflict")
                    raise ValueError("report_not_found")
                row = connection.execute("SELECT * FROM reports WHERE id=? AND user_id=?",
                                         (report.id, report.user_id)).fetchone()
                self._snapshot(connection, row)
                return self._from_row(row)
            created_at = report.created_at.isoformat(timespec="seconds") if report.created_at else utc_now_iso()
            cursor = connection.execute(
                """
                INSERT INTO reports(user_id, type, period_start, period_end, content, created_at,updated_at,provenance)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.user_id,
                    report_type,
                    report.period_start.isoformat(),
                    report.period_end.isoformat(),
                    report.content,
                    created_at,
                    now,
                    provenance,
                ),
            )
            report_id = int(cursor.lastrowid)
            row = connection.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
            self._snapshot(connection, row)
            return self._from_row(row)

    @staticmethod
    def _snapshot(connection, row):
        connection.execute("INSERT INTO report_revisions(report_id,revision,content,saved_at,provenance) VALUES(?,?,?,?,?)",
                           (row["id"], row["revision"], row["content"], row["updated_at"] or row["created_at"], row["provenance"]))
        connection.execute("DELETE FROM report_revisions WHERE report_id=? AND revision NOT IN "
                           "(SELECT revision FROM report_revisions WHERE report_id=? ORDER BY revision DESC LIMIT 50)", (row["id"], row["id"]))

    def list_revisions(self, user_id, report_id):
        with self._connection_factory.connection() as connection:
            rows = connection.execute("SELECT v.* FROM report_revisions v JOIN reports r ON r.id=v.report_id "
                "WHERE r.user_id=? AND r.id=? ORDER BY v.revision DESC LIMIT 50", (user_id, report_id)).fetchall()
        return tuple(ReportRevision(row["revision"], row["content"], parse_datetime(row["saved_at"]), decode_provenance(row["provenance"])) for row in rows)

    def restore_revision(self, user_id, report_id, revision, expected_revision):
        with self._connection_factory.transaction(write=True) as connection:
            row = connection.execute("SELECT * FROM reports WHERE user_id=? AND id=?", (user_id, report_id)).fetchone()
            if row is None:
                raise ValueError("report_not_found")
            if row["revision"] != expected_revision:
                raise ValueError("report_conflict")
            previous = connection.execute("SELECT * FROM report_revisions WHERE report_id=? AND revision=?", (report_id, revision)).fetchone()
            if previous is None:
                raise ValueError("report_not_found")
            connection.execute("UPDATE reports SET content=?,provenance=?,revision=revision+1,updated_at=? WHERE id=?",
                (previous["content"], previous["provenance"], utc_now_iso(), report_id))
            restored = connection.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
            self._snapshot(connection, restored)
            return self._from_row(restored)

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
        return map_rows(rows, self._from_row)

    def remove(self, user_id: int, report_id: int, *, expected_content: str | None = None) -> None:
        with self._connection_factory.transaction(write=True) as connection:
            query = "DELETE FROM reports WHERE user_id=? AND id=?"
            parameters = (user_id, report_id)
            if expected_content is not None:
                query += " AND content=?"
                parameters += (expected_content,)
            if connection.execute(query, parameters).rowcount != 1:
                exists = connection.execute("SELECT 1 FROM reports WHERE user_id=? AND id=?", (user_id, report_id)).fetchone()
                raise ValueError("report_conflict" if exists else "report_not_found")

    def list_range(self, user_id: int, report_type: str, start: date, end: date) -> tuple[Report, ...]:
        with self._connection_factory.connection() as connection:
            rows = connection.execute("SELECT * FROM reports WHERE user_id=? AND type=? AND period_start BETWEEN ? AND ? "
                                      "ORDER BY period_start,created_at DESC,id DESC",
                                      (user_id, normalize_report_type(report_type), start.isoformat(), end.isoformat())).fetchall()
        return map_rows(rows, self._from_row)

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
            revision=int(row["revision"]),
            updated_at=parse_datetime(row["updated_at"]),
            provenance=decode_provenance(row["provenance"]),
        )
