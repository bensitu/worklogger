"""SQLite worklog writes."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from worklogger.domain.worklog.models import WorkLog
from worklogger.domain.worklog.rules import (
    normalize_work_log,
)
from worklogger.domain.worklog.intervals import EntryIntervalIndex
from worklogger.infrastructure.repositories.note_sqlite import save_note
from worklogger.infrastructure.repositories.project_sqlite import validate_record_context
from worklogger.infrastructure.repositories.entry_changes_sqlite import SQLiteEntryChanges
from worklogger.infrastructure.repositories.entry_write_session_sqlite import EntryWriteSession
from worklogger.infrastructure.repositories.import_conflicts_sqlite import remove_import_targets
from worklogger.infrastructure.repositories.recent_context_sqlite import remember_context
from worklogger.infrastructure.repositories.worklog_mapping_sqlite import WorkLogStorage
from worklogger.infrastructure.repositories.worklog_queries_sqlite import (
    SQLiteWorkLogQueries,
)


class SQLiteWorkLogWrites:
    def __init__(self, storage: WorkLogStorage, queries: SQLiteWorkLogQueries, changes: SQLiteEntryChanges):
        self._storage = storage
        self._queries = queries
        self.changes = changes

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
            session = EntryWriteSession(connection, self._storage)
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
                            session.change_timer(record.user_id, *timer_change)
                        return stored
            validate_record_context(connection, record)
            session.check_overlap(record)
            if record.id is None:
                entry_id = session.insert(record)
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
                session.change_timer(record.user_id, *timer_change)
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
            session = EntryWriteSession(connection, self._storage)
            before = self.changes.rows(connection, user_id, (entry_id,))
            cursor = connection.execute(
                "DELETE FROM worklog WHERE user_id=? AND id=? AND revision=?",
                (user_id, entry_id, revision),
            )
            if cursor.rowcount != 1:
                raise ValueError("worklog_entry_conflict")
            if timer_change is not None:
                session.change_timer(user_id, *timer_change)
            self.changes.remember(connection, user_id, "delete", before, [])

    def change_timer(
        self, user_id: int, expected: str | None, value: str | None
    ) -> None:
        with self._storage.connection_factory.transaction() as connection:
            EntryWriteSession(connection, self._storage).change_timer(user_id, expected, value)

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
            session = EntryWriteSession(connection, self._storage)
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
            after = {}
            session.check_overlaps(record for record in records if not record.is_note_only)
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
                identity = session.insert(record)
                after.setdefault((record.user_id, record.day), []).append(identity)
            if overwrite and not daily_replacement:
                for key, previous in before.items():
                    current = self.changes.rows(connection, key[0], after.get(key, ()))
                    if len(current) > 250:
                        raise ValueError("record_change_too_large")
                    if previous or current:
                        self.changes.remember(connection, key[0], "import", previous, current)
