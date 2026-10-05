"""SQLite work log repository."""

from __future__ import annotations

from datetime import date, datetime
import math
import sqlite3

from worklogger.domain.worklog.models import WorkLog
from worklogger.domain.worklog.rules import normalize_work_log, normalize_work_type, parse_time
from worklogger.infrastructure.database.connection import SQLiteConnectionFactory
from worklogger.infrastructure.repositories._mapping import parse_date, map_rows
from worklogger.infrastructure.repositories.note_sqlite import save_note


class SQLiteWorkLogRepository:
    def __init__(self, connection_factory: SQLiteConnectionFactory) -> None:
        self._connection_factory = connection_factory
        with connection_factory.connection() as connection:
            self._separate_notes = connection.execute("SELECT 1 FROM sqlite_master WHERE name='daily_notes'").fetchone() is not None
            self._timestamps = "started_at" in {row[1] for row in connection.execute("PRAGMA table_info(worklog)")}
        self._select = 'SELECT w.user_id, w.d, w.start, w.end, w."break", '
        self._select += ('COALESCE(n.content, w.note) AS note' if self._separate_notes else 'w.note')
        self._select += ', w.work_type, w.overnight'
        if self._timestamps:
            self._select += ', w.started_at, w.ended_at'
        self._select += ' FROM worklog AS w '
        if self._separate_notes:
            self._select += 'LEFT JOIN daily_notes AS n ON n.user_id=w.user_id AND n.d=w.d '

    def get_for_day(self, user_id: int, day: date) -> WorkLog | None:
        with self._connection_factory.connection() as connection:
            row = connection.execute(
                self._select + "WHERE w.user_id=? AND w.d=?",
                (user_id, day.isoformat()),
            ).fetchone()
        return self._from_row(row) if row else None

    def list_for_month(self, user_id: int, year: int, month: int) -> tuple[WorkLog, ...]:
        prefix = f"{int(year):04d}-{int(month):02d}"
        with self._connection_factory.connection() as connection:
            rows = connection.execute(
                self._select + "WHERE w.user_id=? AND w.d BETWEEN ? AND ? ORDER BY w.d",
                (user_id, f"{prefix}-01", f"{prefix}-31"),
            ).fetchall()
        return map_rows(rows, self._from_row)

    def list_range(self, user_id: int, start: date, end: date) -> tuple[WorkLog, ...]:
        with self._connection_factory.connection() as connection:
            rows = connection.execute(self._select + "WHERE w.user_id=? AND w.d BETWEEN ? AND ? ORDER BY w.d",
                                      (user_id, start.isoformat(), end.isoformat())).fetchall()
        return map_rows(rows, self._from_row)

    def list_all(self, user_id: int) -> tuple[WorkLog, ...]:
        with self._connection_factory.connection() as connection:
            rows = connection.execute(
                self._select + "WHERE w.user_id=? ORDER BY w.d",
                (user_id,),
            ).fetchall()
        return map_rows(rows, self._from_row)

    def save(self, work_log: WorkLog, *, expected_note: str | None = None) -> None:
        self.import_many((work_log,), overwrite=True, expected_note=expected_note)

    def list_export_rows(self, user_id: int) -> tuple[WorkLog, ...]:
        records = self.list_all(user_id)
        if not self._separate_notes:
            return records
        with self._connection_factory.connection() as connection:
            rows = connection.execute(
                "SELECT d, content FROM daily_notes WHERE user_id=? AND content<>'' "
                "AND NOT EXISTS (SELECT 1 FROM worklog WHERE worklog.user_id=daily_notes.user_id AND worklog.d=daily_notes.d)",
                (user_id,),
            ).fetchall()
        notes = map_rows(rows, lambda row: WorkLog(user_id, parse_date(row["d"]), note=row["content"]))
        return tuple(sorted((*records, *notes),
                            key=lambda record: record.day))

    def import_many(self, rows: tuple[WorkLog, ...], *, overwrite: bool = False, expected_note: str | None = None) -> None:
        normalized_rows = tuple(normalize_work_log(row) for row in rows)
        if not self._timestamps and any(row.started_at is not None or row.ended_at is not None for row in normalized_rows):
            raise ValueError("database_version_unsupported")
        with self._connection_factory.transaction(write=True) as connection:
            if not overwrite:
                for row in normalized_rows:
                    if connection.execute("SELECT 1 FROM worklog WHERE user_id=? AND d=?",
                                          (row.user_id, row.day.isoformat())).fetchone():
                        raise ValueError("csv_import_conflict")
                    if self._separate_notes and connection.execute(
                        "SELECT 1 FROM daily_notes WHERE user_id=? AND d=? AND content<>''",
                        (row.user_id, row.day.isoformat()),
                    ).fetchone():
                        raise ValueError("csv_import_conflict")
            if self._separate_notes:
                for row in normalized_rows:
                    save_note(connection, row.user_id, row.day, row.note, expected_note)
                note_only_rows = tuple(row for row in normalized_rows if not row.has_times and row.work_type.value == "normal"
                                       and row.break_hours == 0 and bool(row.note))
                for row in note_only_rows:
                    connection.execute("DELETE FROM worklog WHERE user_id=? AND d=?", (row.user_id, row.day.isoformat()))
                note_only_dates = {(row.user_id, row.day) for row in note_only_rows}
                normalized_rows = tuple(row for row in normalized_rows if (row.user_id, row.day) not in note_only_dates)
            connection.executemany(
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
                [(
                    normalized.user_id,
                    normalized.day.isoformat(),
                    normalized.start_time,
                    normalized.end_time,
                    normalized.break_hours,
                    "" if self._separate_notes else normalized.note,
                    normalized.work_type.value,
                    1 if normalized.overnight else 0,
                ) for normalized in normalized_rows],
            )
            if self._timestamps:
                connection.executemany("UPDATE worklog SET started_at=?, ended_at=? WHERE user_id=? AND d=?",
                    [(row.started_at.isoformat() if row.started_at else None,
                      row.ended_at.isoformat() if row.ended_at else None, row.user_id, row.day.isoformat()) for row in normalized_rows])

    def remove(self, user_id: int, day: date) -> None:
        with self._connection_factory.transaction(write=True) as connection:
            connection.execute(
                "DELETE FROM worklog WHERE user_id=? AND d=?",
                (user_id, day.isoformat()),
            )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> WorkLog:
        break_hours = float(row["break"] or 0)
        if not math.isfinite(break_hours) or not 0 <= break_hours <= 24:
            raise ValueError("stored_work_log_invalid")
        record = WorkLog(
            user_id=int(row["user_id"]),
            day=parse_date(row["d"]),
            start_time=parse_time(row["start"]),
            end_time=parse_time(row["end"]),
            break_hours=break_hours,
            note=str(row["note"] or ""),
            work_type=normalize_work_type(row["work_type"]),
            overnight=bool(int(row["overnight"] or 0)),
            started_at=datetime.fromisoformat(row["started_at"]) if "started_at" in row.keys() and row["started_at"] else None,
            ended_at=datetime.fromisoformat(row["ended_at"]) if "ended_at" in row.keys() and row["ended_at"] else None,
        )
        return normalize_work_log(record) if record.started_at is not None or record.ended_at is not None else record
