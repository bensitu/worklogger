"""Worklog repository facade composing queries and writes."""

from __future__ import annotations

from datetime import date

from worklogger.domain.worklog.models import WorkLog
from worklogger.infrastructure.database.connection import SQLiteConnectionFactory
from worklogger.infrastructure.repositories.worklog_mapping_sqlite import WorkLogStorage
from worklogger.infrastructure.repositories.worklog_queries_sqlite import (
    SQLiteWorkLogQueries,
)
from worklogger.infrastructure.repositories.worklog_writes_sqlite import (
    SQLiteWorkLogWrites,
)
from worklogger.infrastructure.repositories.entry_operations_sqlite import SQLiteEntryOperations


class SQLiteWorkLogRepository:
    def __init__(self, connection_factory: SQLiteConnectionFactory):
        storage = WorkLogStorage(connection_factory)
        self.supports_entries = storage.supports_entries
        self.changes_available = storage.change_history
        self._queries = SQLiteWorkLogQueries(storage)
        self._writes = SQLiteWorkLogWrites(storage, self._queries)
        self._operations = SQLiteEntryOperations(storage, self._writes)

    def get_for_day(self, user_id: int, day: date) -> WorkLog | None:
        return self._queries.get_for_day(user_id, day)

    def list_for_month(self, user_id: int, year: int, month: int) -> tuple[WorkLog, ...]:
        return self._queries.list_for_month(user_id, year, month)

    def list_range(self, user_id: int, start: date, end: date) -> tuple[WorkLog, ...]:
        return self._queries.list_range(user_id, start, end)

    def list_entries_range(self, user_id, start, end, *, limit=50001):
        return self._queries.list_entries_range(user_id, start, end, limit=limit)

    def search_entries(self, user_id, criteria, *, cursor=None, limit=100):
        return self._queries.search_entries(user_id, criteria, cursor=cursor, limit=limit)

    def list_all(self, user_id: int) -> tuple[WorkLog, ...]:
        return self._queries.list_all(user_id)

    def save(self, work_log: WorkLog, *, expected_note: str | None = None) -> None:
        return self._writes.save(work_log, expected_note=expected_note)

    def list_export_rows(self, user_id: int) -> tuple[WorkLog, ...]:
        return self._queries.list_export_rows(user_id)

    def import_many(self, rows: tuple[WorkLog, ...], *, overwrite: bool = False, expected_note: str | None = None) -> None:
        return self._writes.import_many(rows, overwrite=overwrite, expected_note=expected_note)

    def remove(self, user_id: int, day: date) -> None:
        return self._writes.remove(user_id, day)

    def list_for_day(self, user_id: int, day: date) -> tuple[WorkLog, ...]:
        return self._queries.list_for_day(user_id, day)

    def get_entry(self, user_id: int, entry_id: int) -> WorkLog | None:
        return self._queries.get_entry(user_id, entry_id)

    def existing_dates(self, user_id: int, dates) -> set[date]:
        return self._queries.existing_dates(user_id, dates)

    def save_entry(self, record: WorkLog, *, timer_change: tuple[str | None, str | None] | None = None) -> WorkLog:
        return self._writes.save_entry(record, timer_change=timer_change)

    def delete_entry(self, user_id: int, entry_id: int, revision: int, *, timer_change: tuple[str | None, str | None] | None = None) -> None:
        return self._writes.delete_entry(user_id, entry_id, revision, timer_change=timer_change)

    def change_timer(self, user_id: int, expected: str | None, value: str | None) -> None:
        return self._writes.change_timer(user_id, expected, value)

    def latest_change(self, user_id):
        return self._writes.changes.latest(user_id)

    def split_entry(self, user_id, record, first_minutes):
        return self._operations.split(user_id, record, first_minutes)

    def merge_entries(self, user_id, left, right):
        return self._operations.merge(user_id, left, right)

    def convert_historical_break(self, user_id, record, first_minutes):
        return self._operations.convert_break(user_id, record, first_minutes)

    def undo_change(self, user_id, change_id):
        return self._operations.undo(user_id, change_id)

    def associate_entries(self, user_id, records, context):
        return self._operations.associate(user_id, records, context)
