"""Atomic interval transformations and conflict-aware compensating changes."""

from dataclasses import replace
from worklogger.domain.worklog.editing import split_entry, split_entry_at, merge_entries, place_historical_break
from worklogger.domain.worklog.replacement import EntryReplacement
from worklogger.domain.worklog.rules import normalize_work_log
from worklogger.domain.projects.models import WorkContext
from worklogger.infrastructure.repositories.project_sqlite import validate_record_context
from worklogger.infrastructure.repositories.recent_context_sqlite import remember_context
from worklogger.infrastructure.repositories.entry_changes_sqlite import SQLiteEntryChanges
from worklogger.infrastructure.repositories.entry_write_session_sqlite import EntryWriteSession
from worklogger.infrastructure.repositories.worklog_mapping_sqlite import WorkLogStorage
from worklogger.infrastructure.repositories.entry_conflicts_sqlite import overlapping_entries


class SQLiteEntryOperations:
    def __init__(self, storage: WorkLogStorage, changes: SQLiteEntryChanges):
        self.storage, self.changes = storage, changes

    @staticmethod
    def _ensure_idle(connection, user_id, *, error_code="auto_record_already_active"):
        row = connection.execute("SELECT value FROM settings WHERE user_id=? AND key='time_entry_timer'", (user_id,)).fetchone()
        if row is not None and row[0]:
            raise ValueError(error_code)

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
        session = EntryWriteSession(connection, self.storage)
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
            session.check_overlap(record)
            identity = session.insert(record, historical=True, preserve_identity=record.id is not None)
            result.append(replace(record, id=identity))
        return tuple(result)

    def _transform(self, user_id, expected, transformation, operation):
        with self.storage.connection_factory.transaction() as connection:
            self._ensure_idle(connection, user_id)
            record = self._load(connection, user_id, expected)
            targets = transformation(record)
            before = self.changes.rows(connection, user_id, (record.id,))
            result = self._replace(connection, user_id, before, targets)
            self.changes.remember(connection, user_id, operation, before,
                self.changes.rows(connection, user_id, [record.id for record in result]))
            return result

    def split(self, user_id, expected, first_minutes):
        return self._transform(user_id, expected, lambda record: split_entry(record, first_minutes), "split")

    def split_at(self, user_id, expected, cut):
        return self._transform(user_id, expected, lambda record: split_entry_at(record, cut), "split")

    def preview_replacement(self, user_id, incoming, original=None):
        if incoming.user_id != user_id or (original is not None and original.user_id != user_id):
            raise ValueError("worklog_entry_conflict")
        with self.storage.connection_factory.transaction(write=False) as connection:
            self._ensure_idle(connection, user_id, error_code="record_replacement_timer_active")
            if original is not None:
                self._load(connection, user_id, original)
            return EntryReplacement(incoming, overlapping_entries(connection, self.storage, incoming), original)

    def replace_overlap(self, user_id, plan, *, keep_outside, remember_work_mode=False):
        if plan.incoming.user_id != user_id:
            raise ValueError("worklog_entry_conflict")
        targets = plan.periods(keep_outside=keep_outside)
        with self.storage.connection_factory.transaction() as connection:
            self._ensure_idle(connection, user_id, error_code="record_replacement_timer_active")
            for expected in plan.affected:
                self._load(connection, user_id, expected)
            validate_record_context(connection, plan.incoming)
            before = self.changes.rows(connection, user_id, [record.id for record in plan.affected])
            result = self._replace(connection, user_id, before, targets)
            self.changes.remember(connection, user_id, "replace", before,
                self.changes.rows(connection, user_id, [record.id for record in result]))
            remember_context(connection, user_id, plan.incoming.context)
            if remember_work_mode and plan.original is None:
                EntryWriteSession(connection, self.storage).remember_work_mode(plan.incoming)
            return result[0]

    def associate(self, user_id, expected, context):
        if (not 1 <= len(expected) <= 250
                or len({entry.id for entry in expected}) != len(expected)
                or any(entry.user_id != user_id or entry.id is None for entry in expected)):
            raise ValueError("record_batch_invalid")
        with self.storage.connection_factory.transaction() as connection:
            self._ensure_idle(connection, user_id)
            records = tuple(self._load(connection, user_id, entry) for entry in expected)
            if context != WorkContext() and any(record.is_break or record.is_leave for record in records):
                raise ValueError("entry_classification_invalid")
            if context.project_id is not None:
                project = connection.execute("SELECT name,archived FROM projects WHERE user_id=? AND id=?", (user_id, context.project_id)).fetchone()
                if project is None or project["archived"]:
                    raise ValueError("project_unavailable")
                item = None
                if context.work_item_id:
                    item = connection.execute("SELECT title,archived FROM work_items WHERE user_id=? AND id=? AND project_id=?",
                                              (user_id, context.work_item_id, context.project_id)).fetchone()
                    if item is None or item["archived"]:
                        raise ValueError("work_item_unavailable")
                context = WorkContext(context.project_id, context.work_item_id, project["name"], item["title"] if item else "")
            elif context.project_label or context.work_item_label:
                raise ValueError("record_batch_invalid")
            targets = tuple(replace(record, context=context) for record in records if record.context != context)
            before = self.changes.rows(connection, user_id, [record.id for record in targets])
            result = []
            for record in targets:
                validate_record_context(connection, record)
                connection.execute("UPDATE worklog SET project_id=?,work_item_id=?,project_label=?,work_item_label=?,revision=revision+1 "
                    "WHERE user_id=? AND id=? AND revision=?", (context.project_id, context.work_item_id, context.project_label,
                    context.work_item_label, user_id, record.id, record.revision))
                result.append(replace(record, revision=record.revision + 1))
            if targets:
                self.changes.remember(connection, user_id, "associate", before,
                    self.changes.rows(connection, user_id, [record.id for record in result]))
                remember_context(connection, user_id, context)
            return tuple(result)

    def convert_break(self, user_id, expected, first_minutes):
        return self._transform(user_id, expected, lambda record: place_historical_break(record, first_minutes), "break")

    def merge(self, user_id, expected_left, expected_right):
        if expected_left.id == expected_right.id:
            raise ValueError("record_merge_invalid")
        with self.storage.connection_factory.transaction() as connection:
            self._ensure_idle(connection, user_id)
            left = self._load(connection, user_id, expected_left)
            right = self._load(connection, user_id, expected_right)
            target = merge_entries(left, right)
            before = self.changes.rows(connection, user_id, (left.id, right.id))
            result = self._replace(connection, user_id, before, (target,))
            self.changes.remember(connection, user_id, "merge", before,
                self.changes.rows(connection, user_id, (result[0].id,)))
            return result[0]

    def undo(self, user_id, change_id):
        with self.storage.connection_factory.transaction() as connection:
            self._ensure_idle(connection, user_id)
            before, after = self.changes.load(connection, user_id, change_id)
            targets = tuple(self.storage.from_row(row) for row in before)
            restored = self._replace(connection, user_id, after, targets)
            self.changes.complete_undo(connection, user_id, change_id,
                self.changes.rows(connection, user_id, [record.id for record in restored]))
            return restored
