"""Atomic interval transformations and conflict-aware compensating changes."""

from dataclasses import replace
from worklogger.domain.worklog.editing import split_entry, merge_entries, place_historical_break
from worklogger.domain.worklog.rules import normalize_work_log


class SQLiteEntryOperations:
    def __init__(self, storage, writes):
        self.storage, self.writes = storage, writes

    @staticmethod
    def _ensure_idle(connection, user_id):
        row = connection.execute("SELECT value FROM settings WHERE user_id=? AND key='time_entry_timer'", (user_id,)).fetchone()
        if row is not None and row[0]:
            raise ValueError("auto_record_already_active")

    def _load(self, connection, user_id, expected):
        row = connection.execute(self.storage.select + " WHERE w.user_id=? AND w.id=?", (user_id, expected.id)).fetchone()
        if row is None:
            raise ValueError("worklog_entry_conflict")
        stored = self.storage.from_row(row)
        if (stored.revision != expected.revision or stored.capture_id != expected.capture_id
                or self.storage.entry_values(stored) != self.storage.entry_values(expected)):
            raise ValueError("worklog_entry_conflict")
        return stored

    def _replace(self, connection, user_id, before, targets):
        previous = {row["id"]: row for row in before}
        for row in before:
            connection.execute("DELETE FROM worklog WHERE user_id=? AND id=?", (user_id, row["id"]))
        result = []
        for target in targets:
            record = normalize_work_log(target)
            if record.user_id != user_id:
                raise ValueError("worklog_entry_conflict")
            if record.id is not None:
                current = previous.get(record.id)
                record = replace(record, revision=max(record.revision, current["revision"] if current else record.revision) + 1)
            self.writes._check_overlap(connection, record)
            identity = self.writes._insert_entry(connection, record, historical=True, preserve_identity=record.id is not None)
            result.append(replace(record, id=identity))
        return tuple(result)

    def _transform(self, user_id, expected, transformation, operation):
        if not self.storage.change_history:
            raise ValueError("record_change_unavailable")
        with self.storage.connection_factory.transaction() as connection:
            self._ensure_idle(connection, user_id)
            record = self._load(connection, user_id, expected)
            targets = transformation(record)
            before = self.writes.changes.rows(connection, user_id, (record.id,))
            result = self._replace(connection, user_id, before, targets)
            self.writes.changes.remember(connection, user_id, operation, before,
                self.writes.changes.rows(connection, user_id, [record.id for record in result]))
            return result

    def split(self, user_id, expected, first_minutes):
        return self._transform(user_id, expected, lambda record: split_entry(record, first_minutes), "split")

    def convert_break(self, user_id, expected, first_minutes):
        return self._transform(user_id, expected, lambda record: place_historical_break(record, first_minutes), "break")

    def merge(self, user_id, expected_left, expected_right):
        if not self.storage.change_history:
            raise ValueError("record_change_unavailable")
        if expected_left.id == expected_right.id:
            raise ValueError("record_merge_invalid")
        with self.storage.connection_factory.transaction() as connection:
            self._ensure_idle(connection, user_id)
            left = self._load(connection, user_id, expected_left)
            right = self._load(connection, user_id, expected_right)
            target = merge_entries(left, right)
            before = self.writes.changes.rows(connection, user_id, (left.id, right.id))
            result = self._replace(connection, user_id, before, (target,))
            self.writes.changes.remember(connection, user_id, "merge", before,
                self.writes.changes.rows(connection, user_id, (result[0].id,)))
            return result[0]

    def undo(self, user_id, change_id):
        if not self.storage.change_history:
            raise ValueError("record_change_unavailable")
        with self.storage.connection_factory.transaction() as connection:
            self._ensure_idle(connection, user_id)
            before, after = self.writes.changes.load(connection, user_id, change_id)
            targets = tuple(self.storage.from_row(row) for row in before)
            restored = self._replace(connection, user_id, after, targets)
            self.writes.changes.complete_undo(connection, user_id, change_id,
                self.writes.changes.rows(connection, user_id, [record.id for record in restored]))
            return restored
