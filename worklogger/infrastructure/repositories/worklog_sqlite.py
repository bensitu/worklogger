"""SQLite work log repository."""

from __future__ import annotations

from datetime import date, datetime
from dataclasses import replace
import math
import sqlite3
import json
from datetime import timezone, timedelta
from worklogger.config.constants import MAX_SHIFT_HOURS

from worklogger.domain.worklog.models import WorkLog
from worklogger.domain.worklog.rules import aggregate_days, entries_overlap, entry_interval, normalize_work_log, normalize_work_type, parse_time
from worklogger.infrastructure.database.connection import SQLiteConnectionFactory
from worklogger.infrastructure.repositories._mapping import parse_date, map_rows
from worklogger.infrastructure.repositories.note_sqlite import save_note


class SQLiteWorkLogRepository:
    def __init__(self, connection_factory: SQLiteConnectionFactory) -> None:
        self._connection_factory = connection_factory
        with connection_factory.connection() as connection:
            self._separate_notes = connection.execute("SELECT 1 FROM sqlite_master WHERE name='daily_notes'").fetchone() is not None
            self._timestamps = "started_at" in {row[1] for row in connection.execute("PRAGMA table_info(worklog)")}
            self.supports_entries = "id" in {row[1] for row in connection.execute("PRAGMA table_info(worklog)")}
        self._select = 'SELECT w.user_id, w.d, w.start, w.end, w."break", '
        self._select += ('COALESCE(n.content, w.note) AS note' if self._separate_notes and not self.supports_entries else 'w.note')
        self._select += ', w.work_type, w.overnight'
        if self._timestamps:
            self._select += ', w.started_at, w.ended_at'
        if self.supports_entries:
            self._select += ', w.id, w.revision, w.capture_id'
        self._select += ' FROM worklog AS w '
        if self._separate_notes and not self.supports_entries:
            self._select += 'LEFT JOIN daily_notes AS n ON n.user_id=w.user_id AND n.d=w.d '

    def get_for_day(self, user_id: int, day: date) -> WorkLog | None:
        if self.supports_entries:
            summaries = aggregate_days(self.list_for_day(user_id, day))
            return summaries[0] if summaries else None
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
        return aggregate_days(map_rows(rows, self._from_row))

    def list_range(self, user_id: int, start: date, end: date) -> tuple[WorkLog, ...]:
        with self._connection_factory.connection() as connection:
            rows = connection.execute(self._select + "WHERE w.user_id=? AND w.d BETWEEN ? AND ? ORDER BY w.d",
                                      (user_id, start.isoformat(), end.isoformat())).fetchall()
        return aggregate_days(map_rows(rows, self._from_row))

    def list_all(self, user_id: int) -> tuple[WorkLog, ...]:
        with self._connection_factory.connection() as connection:
            rows = connection.execute(
                self._select + "WHERE w.user_id=? ORDER BY w.d",
                (user_id,),
            ).fetchall()
        return aggregate_days(map_rows(rows, self._from_row))

    def save(self, work_log: WorkLog, *, expected_note: str | None = None) -> None:
        if self.supports_entries:
            self._import_entries((normalize_work_log(work_log),), overwrite=True, expected_note=expected_note, daily_replacement=True)
            return
        self.import_many((work_log,), overwrite=True, expected_note=expected_note)

    def list_export_rows(self, user_id: int) -> tuple[WorkLog, ...]:
        with self._connection_factory.connection() as connection:
            records = map_rows(connection.execute(self._select + "WHERE w.user_id=? ORDER BY w.d,w.start", (user_id,)).fetchall(), self._from_row)
        if not self._separate_notes:
            return records
        with self._connection_factory.connection() as connection:
            condition = "" if self.supports_entries else "AND NOT EXISTS (SELECT 1 FROM worklog WHERE worklog.user_id=daily_notes.user_id AND worklog.d=daily_notes.d)"
            rows = connection.execute(
                "SELECT d, content FROM daily_notes WHERE user_id=? AND content<>'' " + condition,
                (user_id,),
            ).fetchall()
        notes = map_rows(rows, lambda row: WorkLog(user_id, parse_date(row["d"]), note=row["content"]))
        return tuple(sorted((*records, *notes),
                            key=lambda record: record.day))

    def import_many(self, rows: tuple[WorkLog, ...], *, overwrite: bool = False, expected_note: str | None = None) -> None:
        normalized_rows = tuple(normalize_work_log(row) for row in rows)
        if self.supports_entries:
            self._import_entries(normalized_rows, overwrite=overwrite, expected_note=expected_note)
            return
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

    def list_for_day(self, user_id: int, day: date) -> tuple[WorkLog, ...]:
        with self._connection_factory.connection() as connection:
            rows = connection.execute(self._select + "WHERE w.user_id=? AND w.d=? ORDER BY w.start,w.id", (user_id, day.isoformat())).fetchall()
        return map_rows(rows, self._from_row)

    def get_entry(self, user_id: int, entry_id: int) -> WorkLog | None:
        with self._connection_factory.connection() as connection:
            row = connection.execute(self._select + "WHERE w.user_id=? AND w.id=?", (user_id, entry_id)).fetchone()
        return self._from_row(row) if row else None

    def existing_dates(self, user_id: int, dates) -> set[date]:
        values = tuple(sorted(day.isoformat() for day in dates))
        existing = set()
        with self._connection_factory.connection() as connection:
            for index in range(0, len(values), 256):
                chunk = values[index:index + 256]
                placeholders = ",".join("?" for _ in chunk)
                query = f"SELECT d FROM worklog WHERE user_id=? AND d IN ({placeholders})"
                parameters = (user_id, *chunk)
                if self._separate_notes:
                    query += f" UNION SELECT d FROM daily_notes WHERE user_id=? AND d IN ({placeholders}) AND content<>''"
                    parameters += (user_id, *chunk)
                existing.update(parse_date(row[0]) for row in connection.execute(query, parameters))
        return existing

    def save_entry(self, record: WorkLog, *, timer_change: tuple[str | None, str | None] | None = None) -> WorkLog:
        record = normalize_work_log(record)
        if not record.has_times:
            previous = self.get_entry(record.user_id, record.id) if record.id else None
            if previous is None or previous.has_times or not record.is_leave:
                raise ValueError("time_range_incomplete")
        with self._connection_factory.transaction() as connection:
            if record.capture_id:
                existing = connection.execute(self._select + "WHERE w.user_id=? AND w.capture_id=?", (record.user_id, record.capture_id)).fetchone()
                if existing is not None:
                    stored = self._from_row(existing)
                    if record.id is None:
                        if (stored.day, stored.start_time, stored.end_time, stored.break_hours, stored.started_at, stored.ended_at, stored.note, stored.work_type) != (
                            record.day, record.start_time, record.end_time, record.break_hours, record.started_at, record.ended_at, record.note, record.work_type):
                            raise ValueError("worklog_entry_conflict")
                        if timer_change is not None:
                            self._change_timer(connection, record.user_id, *timer_change)
                        return stored
            self._check_overlap(connection, record)
            if record.id is None:
                entry_id = self._insert_entry(connection, record)
                record = replace(record, id=entry_id)
            else:
                cursor = connection.execute('''UPDATE worklog SET d=?,start=?,end=?,"break"=?,note=?,work_type=?,overnight=?,
                    started_at=?,ended_at=?,revision=revision+1 WHERE user_id=? AND id=? AND revision=?''',
                    (*self._values(record)[1:], record.user_id, record.id, record.revision))
                if cursor.rowcount != 1:
                    raise ValueError("worklog_entry_conflict")
                record = replace(record, revision=record.revision + 1)
            if timer_change is not None:
                self._change_timer(connection, record.user_id, *timer_change)
            return record

    def delete_entry(self, user_id: int, entry_id: int, revision: int, *, timer_change: tuple[str | None, str | None] | None = None) -> None:
        with self._connection_factory.transaction() as connection:
            cursor = connection.execute("DELETE FROM worklog WHERE user_id=? AND id=? AND revision=?", (user_id, entry_id, revision))
            if cursor.rowcount != 1:
                raise ValueError("worklog_entry_conflict")
            if timer_change is not None:
                self._change_timer(connection, user_id, *timer_change)

    def change_timer(self, user_id: int, expected: str | None, value: str | None) -> None:
        with self._connection_factory.transaction() as connection:
            self._change_timer(connection, user_id, expected, value)

    @staticmethod
    def _change_timer(connection, user_id: int, expected: str | None, value: str | None) -> None:
        row = connection.execute("SELECT value FROM settings WHERE user_id=? AND key='time_entry_timer'", (user_id,)).fetchone()
        if (row[0] if row else None) != expected:
            raise ValueError("time_entry_timer_conflict")
        connection.execute("DELETE FROM settings WHERE user_id=? AND key='previous_auto_record_state'", (user_id,))
        if value is None:
            connection.execute("DELETE FROM settings WHERE user_id=? AND key='time_entry_timer'", (user_id,))
        else:
            connection.execute("INSERT INTO settings(user_id,key,value) VALUES(?,'time_entry_timer',?) ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value", (user_id, value))

    def _check_overlap(self, connection, record: WorkLog) -> None:
        timer = connection.execute("SELECT value FROM settings WHERE user_id=? AND key='time_entry_timer'", (record.user_id,)).fetchone()
        if timer and record.has_times:
            state = json.loads(timer[0])
            if state["capture_id"] != record.capture_id:
                start = datetime.fromisoformat(state["started_at"]).astimezone(timezone.utc)
                interval = entry_interval(record)
                if interval[0] < start + timedelta(hours=MAX_SHIFT_HOURS) and start < interval[1]:
                    raise ValueError("worklog_entry_overlap")
        start = max(record.day.toordinal() - 1, date.min.toordinal())
        end = min(record.day.toordinal() + 1, date.max.toordinal())
        rows = connection.execute(self._select + "WHERE w.user_id=? AND w.d BETWEEN ? AND ? AND w.id<>?",
                                  (record.user_id, date.fromordinal(start).isoformat(), date.fromordinal(end).isoformat(), record.id or 0)).fetchall()
        for other in map_rows(rows, self._from_row):
            if entries_overlap(record, other):
                raise ValueError("worklog_entry_overlap")

    def _import_entries(self, records: tuple[WorkLog, ...], *, overwrite: bool, expected_note: str | None,
                        daily_replacement: bool = False) -> None:
        grouped = {}
        for record in records:
            grouped.setdefault((record.user_id, record.day), []).append(record)
        intervals = sorted((record.user_id, *entry_interval(record)) for record in records if record.has_times)
        for left, right in zip(intervals, intervals[1:]):
            if left[0] == right[0] and left[2] > right[1]:
                raise ValueError("worklog_entry_overlap")
        for entries in grouped.values():
            if len([entry for entry in entries if not entry.is_note_only]) > 1 and any(entry.is_leave and not entry.has_times for entry in entries):
                raise ValueError("worklog_entry_overlap")
        with self._connection_factory.transaction() as connection:
            for (user_id, day), entries in grouped.items():
                if daily_replacement and connection.execute("SELECT COUNT(*) FROM worklog WHERE user_id=? AND d=?", (user_id, day.isoformat())).fetchone()[0] > 1:
                    raise ValueError("worklog_summary_not_editable")
                if not overwrite:
                    if connection.execute("SELECT 1 FROM worklog WHERE user_id=? AND d=?", (user_id, day.isoformat())).fetchone():
                        raise ValueError("csv_import_conflict")
                    if connection.execute("SELECT 1 FROM daily_notes WHERE user_id=? AND d=? AND content<>''", (user_id, day.isoformat())).fetchone():
                        raise ValueError("csv_import_conflict")
                if len(entries) == 1:
                    save_note(connection, user_id, day, entries[0].note, expected_note)
                if overwrite:
                    connection.execute("DELETE FROM worklog WHERE user_id=? AND d=?", (user_id, day.isoformat()))
            for record in records:
                if not record.is_note_only:
                    self._check_overlap(connection, record)
            for record in records:
                if not record.has_times and record.work_type.value == "normal" and record.note:
                    save_note(connection, record.user_id, record.day, record.note, expected_note)
                    continue
                self._insert_entry(connection, record)

    @staticmethod
    def _values(record: WorkLog) -> tuple:
        return (record.user_id, record.day.isoformat(), record.start_time, record.end_time, record.break_hours,
                record.note, record.work_type.value, int(record.is_overnight),
                record.started_at.isoformat() if record.started_at else None,
                record.ended_at.isoformat() if record.ended_at else None)

    def _insert_entry(self, connection, record: WorkLog) -> int:
        cursor = connection.execute('''INSERT INTO worklog(user_id,d,start,end,"break",note,work_type,overnight,started_at,ended_at,capture_id)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)''', (*self._values(record), record.capture_id))
        return cursor.lastrowid

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
            id=int(row["id"]) if "id" in row.keys() else None,
            revision=int(row["revision"]) if "revision" in row.keys() else 0,
            capture_id=row["capture_id"] if "capture_id" in row.keys() else None,
        )
        return normalize_work_log(record) if record.started_at is not None or record.ended_at is not None else record
