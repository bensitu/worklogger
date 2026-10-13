"""SQLite worklog writes."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

from worklogger.config.constants import MAX_SHIFT_HOURS
from worklogger.domain.worklog.models import WorkLog
from worklogger.domain.worklog.timer_state import timer_payload
from worklogger.domain.projects.models import WorkContext
from worklogger.domain.worklog.rules import (
    entries_overlap,
    normalize_work_log,
)
from worklogger.domain.worklog.intervals import EntryIntervalIndex
from worklogger.infrastructure.repositories._mapping import map_rows
from worklogger.infrastructure.repositories.note_sqlite import save_note
from worklogger.infrastructure.repositories.project_sqlite import validate_record_context
from worklogger.infrastructure.repositories.entry_changes_sqlite import SQLiteEntryChanges
from worklogger.infrastructure.repositories.import_conflicts_sqlite import remove_import_targets
from worklogger.infrastructure.repositories.recent_context_sqlite import remember_context
from worklogger.infrastructure.repositories.worklog_mapping_sqlite import WorkLogStorage
from worklogger.infrastructure.repositories.worklog_queries_sqlite import (
    SQLiteWorkLogQueries,
)


class SQLiteWorkLogWrites:
    def __init__(self, storage: WorkLogStorage, queries: SQLiteWorkLogQueries):
        self._storage = storage
        self._queries = queries
        self.changes = SQLiteEntryChanges(storage)

    def save(self, work_log: WorkLog, *, expected_note: str | None = None) -> None:
        self._import_entries((normalize_work_log(work_log),), overwrite=True, expected_note=expected_note, daily_replacement=True)

    def import_many(self, rows: tuple[WorkLog, ...], *, overwrite: bool = False,
                    replace_dates: bool = False, expected_note: str | None = None) -> None:
        self._import_entries(tuple(normalize_work_log(row) for row in rows), overwrite=overwrite,
                             replace_dates=replace_dates, expected_note=expected_note)

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
        if not record.has_times:
            previous = (
                self._queries.get_entry(record.user_id, record.id)
                if record.id
                else None
            )
            if previous is None or previous.has_times or not record.is_leave:
                raise ValueError("time_range_incomplete")
        with self._storage.connection_factory.transaction() as connection:
            before = self.changes.rows(connection, record.user_id, (record.id,)) if record.id is not None else []
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
            validate_record_context(connection, record)
            self._check_overlap(connection, record)
            if record.id is None:
                entry_id = self._insert_entry(connection, record)
                record = replace(record, id=entry_id)
            else:
                snapshots = ",work_type_label=?,work_type_category=?,project_id=?,work_item_id=?,project_label=?,work_item_label=?"
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
            self.changes.remember(connection, record.user_id, "update" if before else "create", before,
                                  self.changes.rows(connection, record.user_id, (record.id,)))
            remember_context(connection, record.user_id, record.context)
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
            before = self.changes.rows(connection, user_id, (entry_id,))
            cursor = connection.execute(
                "DELETE FROM worklog WHERE user_id=? AND id=? AND revision=?",
                (user_id, entry_id, revision),
            )
            if cursor.rowcount != 1:
                raise ValueError("worklog_entry_conflict")
            if timer_change is not None:
                self._change_timer(connection, user_id, *timer_change)
            self.changes.remember(connection, user_id, "delete", before, [])

    def change_timer(
        self, user_id: int, expected: str | None, value: str | None
    ) -> None:
        with self._storage.connection_factory.transaction() as connection:
            self._change_timer(connection, user_id, expected, value)

    def _change_timer(
        self, connection, user_id: int, expected: str | None, value: str | None
    ) -> None:
        row = connection.execute(
            "SELECT value FROM settings WHERE user_id=? AND key='time_entry_timer'",
            (user_id,),
        ).fetchone()
        if (row[0] if row else None) != expected:
            raise ValueError("time_entry_timer_conflict")
        if value is not None:
            data = timer_payload(value)
            previous = timer_payload(row[0]) if row else {}
            if data.get("context"):
                validate_record_context(connection, WorkLog(user_id, date.fromisoformat(data["started_at"][:10]),
                    capture_id=previous.get("capture_id"), context=WorkContext(**data["context"])))
            if data["capture_id"] != previous.get("capture_id"):
                start = datetime.fromisoformat(data["started_at"])
                try:
                    end = (start.astimezone(timezone.utc) + timedelta(microseconds=1)).astimezone(start.tzinfo)
                except OverflowError as exc:
                    raise ValueError("auto_record_restore_failed") from exc
                point = WorkLog(user_id, start.date(), start.strftime("%H:%M"), end.strftime("%H:%M"),
                                started_at=start, ended_at=end, capture_id=previous.get("capture_id"))
                self._check_overlap(connection, point)
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

    def _check_overlap(self, connection, record: WorkLog, *, cached_rows=None) -> None:
        timer = connection.execute(
            "SELECT value FROM settings WHERE user_id=? AND key='time_entry_timer'",
            (record.user_id,),
        ).fetchone()
        if timer and record.has_times:
            state = timer_payload(timer[0])
            if state["capture_id"] != record.capture_id:
                start = datetime.fromisoformat(state["started_at"])
                try:
                    end = (start.astimezone(timezone.utc) + timedelta(hours=MAX_SHIFT_HOURS)).astimezone(start.tzinfo)
                except OverflowError as exc:
                    raise ValueError("auto_record_restore_failed") from exc
                reserved = WorkLog(record.user_id, start.date(), start.strftime("%H:%M"), end.strftime("%H:%M"),
                                   started_at=start, ended_at=end)
                if entries_overlap(record, reserved):
                    raise ValueError("worklog_entry_overlap")
        key = (record.user_id, record.day)
        if cached_rows is None or key not in cached_rows:
            start = max(record.day.toordinal() - 3, date.min.toordinal())
            end = min(record.day.toordinal() + 3, date.max.toordinal())
            rows = connection.execute(self._storage.select + "WHERE w.user_id=? AND w.d BETWEEN ? AND ?",
                                      (record.user_id, date.fromordinal(start).isoformat(), date.fromordinal(end).isoformat())).fetchall()
            others = map_rows(rows, self._storage.from_row)
            if cached_rows is not None:
                cached_rows[key] = others
        else:
            others = cached_rows[key]
        for other in others:
            if other.id != record.id and entries_overlap(record, other):
                raise ValueError("worklog_entry_overlap")

    def _import_entries(
        self,
        records: tuple[WorkLog, ...],
        *,
        overwrite: bool,
        expected_note: str | None,
        daily_replacement: bool = False,
        replace_dates: bool = False,
    ) -> None:
        grouped = {}
        for record in records:
            grouped.setdefault((record.user_id, record.day), []).append(record)
        intervals = EntryIntervalIndex(records)
        for record in records:
            if not intervals.add(record):
                raise ValueError("worklog_entry_overlap")
        for entries in grouped.values():
            if len([entry for entry in entries if not entry.is_note_only]) > 1 and any(
                entry.is_leave and not entry.has_times for entry in entries
            ):
                raise ValueError("worklog_entry_overlap")
        with self._storage.connection_factory.transaction() as connection:
            before = {}
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
                if daily_replacement and expected_note is not None and not entries[0].is_note_only:
                    previous = connection.execute("SELECT note FROM worklog WHERE user_id=? AND d=?",
                                                  (user_id, day.isoformat())).fetchone()
                    if (str(previous[0] or "") if previous else "") != expected_note:
                        raise ValueError("note_conflict")
                if overwrite:
                    if daily_replacement:
                        connection.execute("DELETE FROM worklog WHERE user_id=? AND d=?", (user_id, day.isoformat()))
                    else:
                        before[user_id, day] = remove_import_targets(connection, self._storage, user_id, day, entries, replace_dates)
            cached_rows = {}
            after = {}
            for record in records:
                if not record.is_note_only:
                    self._check_overlap(connection, record, cached_rows=cached_rows)
            for record in records:
                if record.is_note_only:
                    save_note(
                        connection,
                        record.user_id,
                        record.day,
                        record.note,
                        expected_note,
                    )
                    continue
                identity = self._insert_entry(connection, record)
                after.setdefault((record.user_id, record.day), []).append(identity)
            if overwrite and not daily_replacement:
                for key, previous in before.items():
                    current = self.changes.rows(connection, key[0], after.get(key, ()))
                    if len(current) > 250:
                        raise ValueError("record_change_too_large")
                    if previous or current:
                        self.changes.remember(connection, key[0], "import", previous, current)

    def _insert_entry(self, connection, record: WorkLog, *, historical=False, preserve_identity=False) -> int:
        columns = (
            'user_id,d,start,end,"break",note,work_type,overnight,started_at,ended_at'
        )
        columns += ",work_type_label,work_type_category"
        validate_record_context(connection, record, historical=historical)
        columns += ",project_id,work_item_id,project_label,work_item_label"
        values = (*self._storage.entry_values(record), record.capture_id)
        columns += ",capture_id"
        if preserve_identity:
            columns += ",id,revision"
            values += (record.id, record.revision)
        cursor = connection.execute(
            f"INSERT INTO worklog({columns}) VALUES({','.join('?' for _ in values)})",
            values,
        )
        return cursor.lastrowid
