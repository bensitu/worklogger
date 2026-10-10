"""SQLite worklog writes."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

from worklogger.config.constants import MAX_SHIFT_HOURS
from worklogger.domain.worklog.models import CustomWorkType, WorkLog
from worklogger.domain.projects.models import WorkContext
from worklogger.domain.worklog.rules import (
    entries_overlap,
    entry_interval,
    normalize_work_log,
)
from worklogger.infrastructure.repositories._mapping import map_rows
from worklogger.infrastructure.repositories.note_sqlite import save_note
from worklogger.infrastructure.repositories.project_sqlite import validate_record_context
from worklogger.infrastructure.repositories.worklog_mapping_sqlite import WorkLogStorage
from worklogger.infrastructure.repositories.worklog_queries_sqlite import (
    SQLiteWorkLogQueries,
)


class SQLiteWorkLogWrites:
    def __init__(self, storage: WorkLogStorage, queries: SQLiteWorkLogQueries):
        self._storage = storage
        self._queries = queries

    def save(self, work_log: WorkLog, *, expected_note: str | None = None) -> None:
        if self._storage.supports_entries:
            self._import_entries(
                (normalize_work_log(work_log),),
                overwrite=True,
                expected_note=expected_note,
                daily_replacement=True,
            )
            return
        self.import_many((work_log,), overwrite=True, expected_note=expected_note)

    def import_many(
        self,
        rows: tuple[WorkLog, ...],
        *,
        overwrite: bool = False,
        expected_note: str | None = None,
    ) -> None:
        normalized_rows = tuple(normalize_work_log(row) for row in rows)
        if not self._storage.type_snapshots and any(
            isinstance(row.work_type, CustomWorkType) for row in normalized_rows
        ):
            raise ValueError("database_version_unsupported")
        if self._storage.supports_entries:
            self._import_entries(
                normalized_rows, overwrite=overwrite, expected_note=expected_note
            )
            return
        if not self._storage.timestamps and any(
            row.started_at is not None or row.ended_at is not None
            for row in normalized_rows
        ):
            raise ValueError("database_version_unsupported")
        with self._storage.connection_factory.transaction(write=True) as connection:
            if not overwrite:
                for row in normalized_rows:
                    if connection.execute(
                        "SELECT 1 FROM worklog WHERE user_id=? AND d=?",
                        (row.user_id, row.day.isoformat()),
                    ).fetchone():
                        raise ValueError("csv_import_conflict")
                    if (
                        self._storage.separate_notes
                        and connection.execute(
                            "SELECT 1 FROM daily_notes WHERE user_id=? AND d=? AND content<>''",
                            (row.user_id, row.day.isoformat()),
                        ).fetchone()
                    ):
                        raise ValueError("csv_import_conflict")
            if self._storage.separate_notes:
                for row in normalized_rows:
                    save_note(connection, row.user_id, row.day, row.note, expected_note)
                note_only_rows = tuple(
                    row
                    for row in normalized_rows
                    if not row.has_times
                    and row.work_type.value == "normal"
                    and row.break_hours == 0
                    and bool(row.note)
                )
                for row in note_only_rows:
                    connection.execute(
                        "DELETE FROM worklog WHERE user_id=? AND d=?",
                        (row.user_id, row.day.isoformat()),
                    )
                note_only_dates = {(row.user_id, row.day) for row in note_only_rows}
                normalized_rows = tuple(
                    row
                    for row in normalized_rows
                    if (row.user_id, row.day) not in note_only_dates
                )
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
                [
                    (
                        normalized.user_id,
                        normalized.day.isoformat(),
                        normalized.start_time,
                        normalized.end_time,
                        normalized.break_hours,
                        "" if self._storage.separate_notes else normalized.note,
                        normalized.work_type.value,
                        1 if normalized.overnight else 0,
                    )
                    for normalized in normalized_rows
                ],
            )
            if self._storage.timestamps:
                connection.executemany(
                    "UPDATE worklog SET started_at=?, ended_at=? WHERE user_id=? AND d=?",
                    [
                        (
                            row.started_at.isoformat() if row.started_at else None,
                            row.ended_at.isoformat() if row.ended_at else None,
                            row.user_id,
                            row.day.isoformat(),
                        )
                        for row in normalized_rows
                    ],
                )

    def remove(self, user_id: int, day: date) -> None:
        with self._storage.connection_factory.transaction(write=True) as connection:
            connection.execute(
                "DELETE FROM worklog WHERE user_id=? AND d=?",
                (user_id, day.isoformat()),
            )

    def save_entry(
        self,
        record: WorkLog,
        *,
        timer_change: tuple[str | None, str | None] | None = None,
    ) -> WorkLog:
        record = normalize_work_log(record)
        if (
            isinstance(record.work_type, CustomWorkType)
            and not self._storage.type_snapshots
        ):
            raise ValueError("database_version_unsupported")
        if not record.has_times:
            previous = (
                self._queries.get_entry(record.user_id, record.id)
                if record.id
                else None
            )
            if previous is None or previous.has_times or not record.is_leave:
                raise ValueError("time_range_incomplete")
        with self._storage.connection_factory.transaction() as connection:
            if record.capture_id:
                existing = connection.execute(
                    self._storage.select + "WHERE w.user_id=? AND w.capture_id=?",
                    (record.user_id, record.capture_id),
                ).fetchone()
                if existing is not None:
                    stored = self._storage.from_row(existing)
                    if record.id is None:
                        if (
                            stored.day,
                            stored.start_time,
                            stored.end_time,
                            stored.break_hours,
                            stored.started_at,
                            stored.ended_at,
                            stored.note,
                            stored.work_type,
                            stored.context,
                        ) != (
                            record.day,
                            record.start_time,
                            record.end_time,
                            record.break_hours,
                            record.started_at,
                            record.ended_at,
                            record.note,
                            record.work_type,
                            record.context,
                        ):
                            raise ValueError("worklog_entry_conflict")
                        if timer_change is not None:
                            self._change_timer(
                                connection, record.user_id, *timer_change
                            )
                        return stored
            if self._storage.work_context:
                validate_record_context(connection, record)
            self._check_overlap(connection, record)
            if record.id is None:
                entry_id = self._insert_entry(connection, record)
                record = replace(record, id=entry_id)
            else:
                snapshots = (
                    ",work_type_label=?,work_type_category=?"
                    if self._storage.type_snapshots
                    else ""
                )
                if self._storage.work_context:
                    snapshots += ",project_id=?,work_item_id=?,project_label=?,work_item_label=?"
                cursor = connection.execute(
                    """UPDATE worklog SET d=?,start=?,end=?,"break"=?,note=?,work_type=?,overnight=?,
                    started_at=?,ended_at=?"""
                    + snapshots
                    + """,revision=revision+1 WHERE user_id=? AND id=? AND revision=?""",
                    (
                        *self._storage.entry_values(record)[1:],
                        record.user_id,
                        record.id,
                        record.revision,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ValueError("worklog_entry_conflict")
                record = replace(record, revision=record.revision + 1)
            if timer_change is not None:
                self._change_timer(connection, record.user_id, *timer_change)
            return record

    def delete_entry(
        self,
        user_id: int,
        entry_id: int,
        revision: int,
        *,
        timer_change: tuple[str | None, str | None] | None = None,
    ) -> None:
        with self._storage.connection_factory.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM worklog WHERE user_id=? AND id=? AND revision=?",
                (user_id, entry_id, revision),
            )
            if cursor.rowcount != 1:
                raise ValueError("worklog_entry_conflict")
            if timer_change is not None:
                self._change_timer(connection, user_id, *timer_change)

    def change_timer(
        self, user_id: int, expected: str | None, value: str | None
    ) -> None:
        with self._storage.connection_factory.transaction() as connection:
            self._change_timer(connection, user_id, expected, value)

    @staticmethod
    def _change_timer(
        connection, user_id: int, expected: str | None, value: str | None
    ) -> None:
        row = connection.execute(
            "SELECT value FROM settings WHERE user_id=? AND key='time_entry_timer'",
            (user_id,),
        ).fetchone()
        if (row[0] if row else None) != expected:
            raise ValueError("time_entry_timer_conflict")
        if value is not None:
            data = json.loads(value)
            if data.get("context"):
                previous = json.loads(row[0]) if row else {}
                validate_record_context(connection, WorkLog(user_id, date.fromisoformat(data["started_at"][:10]),
                    capture_id=previous.get("capture_id"), context=WorkContext(**data["context"])))
        connection.execute(
            "DELETE FROM settings WHERE user_id=? AND key='previous_auto_record_state'",
            (user_id,),
        )
        if value is None:
            connection.execute(
                "DELETE FROM settings WHERE user_id=? AND key='time_entry_timer'",
                (user_id,),
            )
        else:
            connection.execute(
                "INSERT INTO settings(user_id,key,value) VALUES(?,'time_entry_timer',?) ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value",
                (user_id, value),
            )

    def _check_overlap(self, connection, record: WorkLog) -> None:
        timer = connection.execute(
            "SELECT value FROM settings WHERE user_id=? AND key='time_entry_timer'",
            (record.user_id,),
        ).fetchone()
        if timer and record.has_times:
            state = json.loads(timer[0])
            if state["capture_id"] != record.capture_id:
                start = datetime.fromisoformat(state["started_at"]).astimezone(
                    timezone.utc
                )
                interval = entry_interval(record)
                if (
                    interval[0] < start + timedelta(hours=MAX_SHIFT_HOURS)
                    and start < interval[1]
                ):
                    raise ValueError("worklog_entry_overlap")
        start = max(record.day.toordinal() - 1, date.min.toordinal())
        end = min(record.day.toordinal() + 1, date.max.toordinal())
        rows = connection.execute(
            self._storage.select
            + "WHERE w.user_id=? AND w.d BETWEEN ? AND ? AND w.id<>?",
            (
                record.user_id,
                date.fromordinal(start).isoformat(),
                date.fromordinal(end).isoformat(),
                record.id or 0,
            ),
        ).fetchall()
        for other in map_rows(rows, self._storage.from_row):
            if entries_overlap(record, other):
                raise ValueError("worklog_entry_overlap")

    def _import_entries(
        self,
        records: tuple[WorkLog, ...],
        *,
        overwrite: bool,
        expected_note: str | None,
        daily_replacement: bool = False,
    ) -> None:
        grouped = {}
        for record in records:
            grouped.setdefault((record.user_id, record.day), []).append(record)
        intervals = sorted(
            (record.user_id, *entry_interval(record))
            for record in records
            if record.has_times
        )
        for left, right in zip(intervals, intervals[1:]):
            if left[0] == right[0] and left[2] > right[1]:
                raise ValueError("worklog_entry_overlap")
        for entries in grouped.values():
            if len([entry for entry in entries if not entry.is_note_only]) > 1 and any(
                entry.is_leave and not entry.has_times for entry in entries
            ):
                raise ValueError("worklog_entry_overlap")
        with self._storage.connection_factory.transaction() as connection:
            for (user_id, day), entries in grouped.items():
                if (
                    daily_replacement
                    and connection.execute(
                        "SELECT COUNT(*) FROM worklog WHERE user_id=? AND d=?",
                        (user_id, day.isoformat()),
                    ).fetchone()[0]
                    > 1
                ):
                    raise ValueError("worklog_summary_not_editable")
                if not overwrite:
                    if connection.execute(
                        "SELECT 1 FROM worklog WHERE user_id=? AND d=?",
                        (user_id, day.isoformat()),
                    ).fetchone():
                        raise ValueError("csv_import_conflict")
                    if connection.execute(
                        "SELECT 1 FROM daily_notes WHERE user_id=? AND d=? AND content<>''",
                        (user_id, day.isoformat()),
                    ).fetchone():
                        raise ValueError("csv_import_conflict")
                if len(entries) == 1:
                    save_note(connection, user_id, day, entries[0].note, expected_note)
                if overwrite:
                    connection.execute(
                        "DELETE FROM worklog WHERE user_id=? AND d=?",
                        (user_id, day.isoformat()),
                    )
            for record in records:
                if not record.is_note_only:
                    self._check_overlap(connection, record)
            for record in records:
                if (
                    not record.has_times
                    and record.work_type.value == "normal"
                    and record.note
                ):
                    save_note(
                        connection,
                        record.user_id,
                        record.day,
                        record.note,
                        expected_note,
                    )
                    continue
                self._insert_entry(connection, record)

    def _insert_entry(self, connection, record: WorkLog) -> int:
        columns = (
            'user_id,d,start,end,"break",note,work_type,overnight,started_at,ended_at'
        )
        if self._storage.type_snapshots:
            columns += ",work_type_label,work_type_category"
        if self._storage.work_context:
            validate_record_context(connection, record)
            columns += ",project_id,work_item_id,project_label,work_item_label"
        values = (*self._storage.entry_values(record), record.capture_id)
        cursor = connection.execute(
            f"INSERT INTO worklog({columns},capture_id) VALUES({','.join('?' for _ in values)})",
            values,
        )
        return cursor.lastrowid
