"""Shared entry writes within a caller-owned SQLite transaction."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from sqlite3 import Connection

from worklogger.config.constants import MAX_SHIFT_HOURS
from worklogger.domain.projects.models import WorkContext
from worklogger.domain.worklog.models import WorkLog
from worklogger.domain.worklog.rules import entries_overlap
from worklogger.domain.worklog.timer_state import timer_payload
from worklogger.infrastructure.repositories._mapping import map_rows
from worklogger.infrastructure.repositories.project_sqlite import validate_record_context
from worklogger.infrastructure.repositories.worklog_mapping_sqlite import WorkLogStorage


class EntryWriteSession:
    """Use an existing transaction without opening or committing connections."""

    def __init__(self, connection: Connection, storage: WorkLogStorage) -> None:
        if not connection.in_transaction:
            raise RuntimeError("entry_write_requires_transaction")
        self._connection = connection
        self._storage = storage

    def check_overlap(self, record: WorkLog) -> None:
        self._check_overlap(record)

    def check_overlaps(self, records: Iterable[WorkLog]) -> None:
        """Validate against stored rows, reusing reads only during this pass."""
        cached_rows, cached_timers = {}, {}
        for record in records:
            self._check_overlap(record, cached_rows=cached_rows, cached_timers=cached_timers)

    def _check_overlap(self, record: WorkLog, *, cached_rows=None, cached_timers=None) -> None:
        connection = self._connection
        if cached_timers is not None and record.user_id in cached_timers:
            timer = cached_timers[record.user_id]
        else:
            timer = connection.execute(
                "SELECT value FROM settings WHERE user_id=? AND key='time_entry_timer'",
                (record.user_id,),
            ).fetchone()
            if cached_timers is not None:
                cached_timers[record.user_id] = timer
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

    def insert(self, record: WorkLog, *, historical: bool = False, preserve_identity: bool = False) -> int:
        columns = 'user_id,d,start,end,"break",note,work_type,overnight,started_at,ended_at'
        columns += ",work_type_label,work_type_category"
        validate_record_context(self._connection, record, historical=historical)
        columns += ",project_id,work_item_id,project_label,work_item_label"
        values = (*self._storage.entry_values(record), record.capture_id)
        columns += ",capture_id"
        if preserve_identity:
            columns += ",id,revision"
            values += (record.id, record.revision)
        cursor = self._connection.execute(
            f"INSERT INTO worklog({columns}) VALUES({','.join('?' for _ in values)})",
            values,
        )
        return cursor.lastrowid

    def change_timer(self, user_id: int, expected: str | None, value: str | None) -> None:
        connection = self._connection
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
                self.check_overlap(point)
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
