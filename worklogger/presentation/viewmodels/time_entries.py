"""Presentation state for manual and automatic time-entry editing."""

from __future__ import annotations

from dataclasses import replace
from collections.abc import Callable
from datetime import date
from enum import Enum
from typing import TypeVar

from worklogger.app.recording_ports import TimeEntryOperations
from worklogger.app.commands.ai_commands import RewriteTextCommand
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import EntryCategory, EntryType, WorkLog, WorkModeValue
from worklogger.domain.worklog.content import require_entry_content
from worklogger.domain.projects.models import WorkContext
from worklogger.domain.worklog.rules import timestamp_span_hours
from worklogger.domain.worklog.editing import merge_entries
from worklogger.domain.worklog.reminders import timer_reminders
from worklogger.presentation.viewmodels.time_entry_editor import TimeEntryEditorState, editor_state
from worklogger.presentation.viewmodels.time_entry_operations import (
    TimeEntryDraft as TimeEntryDraft, TimeEntryEditState, TimeEntryOperationRequest, TimeEntryOperationResult,
)

T = TypeVar("T")


class _Unset(Enum):
    WORK_MODE = 0


class TimeEntryViewModel:
    def editor_state(self, *, automatic: bool) -> TimeEntryEditorState:
        return editor_state(self, automatic=automatic)

    def snapshot_state(self) -> TimeEntryEditState:
        return TimeEntryEditState(draft=self.draft, baseline=self._baseline, entries=self.entries,
            auto_completed=self.auto_completed, auto_content=self.auto_content,
            auto_entry_type=self.auto_entry_type, auto_context=self.auto_context,
            auto_work_mode=self.auto_work_mode,
            custom_types=self._custom_types,
            latest_change=self.latest_change_info, timer_origin=self._timer_origin,
            timer_shares_draft=self._timer_shares_draft)

    def _apply_editor_state(self, state: TimeEntryEditState) -> None:
        self.draft, self._baseline, self.entries = state.draft, state.baseline, state.entries
        self.auto_completed, self.auto_content = state.auto_completed, state.auto_content
        self.auto_entry_type, self.auto_context = state.auto_entry_type, state.auto_context
        self.auto_work_mode = state.auto_work_mode
        self._custom_types = state.custom_types
        self.latest_change_info = state.latest_change
        self._timer_origin, self._timer_shares_draft = state.timer_origin, state.timer_shares_draft

    def prepare_operation(self, operation: Callable[[TimeEntryViewModel], Result[T]]) -> Callable[[], Result[TimeEntryOperationResult[T]]]:
        request = TimeEntryOperationRequest(self.snapshot_state(), self.default_break_hours)
        service = self.service.new_session(self.service.snapshot_state())
        return lambda: request.execute(service, operation)

    def apply_operation_result(self, result: TimeEntryOperationResult[T]) -> Result[T]:
        self._apply_editor_state(result.editor)
        self.service.apply_state(result.recording)
        return result.outcome

    def __init__(self, service: TimeEntryOperations, *, default_break_hours: float = 1,
                 rewrite_handler=None, language="en_US", initial_state: TimeEntryEditState | None = None) -> None:
        self.service = service
        self._rewrite_handler, self._language = rewrite_handler, language
        self.default_break_hours = default_break_hours
        self.draft = TimeEntryDraft(service.now().date(), work_mode=service.default_work_mode())
        self._baseline = self.draft
        self.entries = ()
        self.auto_completed: WorkLog | None = None
        self.auto_content = service.timer.content if service.timer else ""
        self.auto_entry_type = service.timer.entry_type.value if service.timer else "normal"
        self.auto_context = service.timer.context if service.timer else WorkContext()
        self.auto_work_mode = service.timer.work_mode if service.timer else self.draft.work_mode
        self._custom_types = None
        self.latest_change_info = None
        self.timer_reminder_hours = 10.0
        self.continuous_timer_reminder_hours = 0.0
        self._timer_origin: TimeEntryDraft | None = None
        self._timer_shares_draft = False
        if initial_state is not None:
            self._apply_editor_state(initial_state)

    def set_timer_reminders(self, long_hours, continuous_hours):
        self.timer_reminder_hours = long_hours
        self.continuous_timer_reminder_hours = continuous_hours

    def reminder_reasons(self):
        timer = self.timer
        return timer_reminders(timer.started_at, self.now(), timer.entry_type, long_hours=self.timer_reminder_hours,
                               continuous_hours=self.continuous_timer_reminder_hours) if timer else ()

    @property
    def projects_available(self):
        return self.service.projects is not None

    def project_inventory(self):
        if not self.projects_available:
            return Result.success(((), {}))
        return self.service.projects.catalog()

    def recent_contexts(self):
        return self.service.projects.recent_contexts() if self.projects_available else Result.success(())

    def validate_selection(self, entry_type, work_mode, context, *, automatic=False):
        state = self.editor_state(automatic=automatic)
        if state.active_timer is not None:
            return Result.failure(ValidationError("auto_record_already_active", "auto_record_already_active"))
        return self.service.validate_selection(entry_type, work_mode, context, state.selected_record, automatic=automatic)

    def associate(self, records, context):
        return self.service.associate(records, context)

    @property
    def search_available(self):
        return self.service.search_available

    def search(self, criteria, *, cursor=None):
        return self.service.search(criteria, cursor=cursor)

    @property
    def changes_available(self):
        return self.service.changes_available

    def merge_candidate(self, record):
        index = next((index for index, entry in enumerate(self.entries) if entry.id == record.id), -1)
        if index < 1:
            return None
        previous = self.entries[index - 1]
        try:
            merge_entries(previous, record)
            return previous
        except ValueError:
            return None

    def latest_change(self):
        return self.service.latest_change()

    def _changed(self, result):
        if result.ok:
            self.clear(self.draft.day)
            self.auto_completed = None
            self.auto_content = ""
        return result

    def split(self, record, first_minutes):
        return self._changed(self.service.split(record, first_minutes))

    def split_at(self, record, cut):
        return self._changed(self.service.split_at(record, cut))

    def replace_overlap(self, plan, *, keep_outside):
        result = self.service.replace_overlap(plan, keep_outside=keep_outside)
        if result.ok:
            self.select(result.value)
        return result

    def merge(self, left, right):
        return self._changed(self.service.merge(left, right))

    def convert_break(self, record, first_minutes):
        return self._changed(self.service.convert_break(record, first_minutes))

    def undo(self, change_id):
        return self._changed(self.service.undo(change_id))

    @property
    def timer(self):
        return self.service.timer

    @property
    def restore_failed(self):
        return self.service.restore_failed

    @property
    def events_deletable(self):
        return self.service.events_deletable

    def now(self):
        return self.service.now()

    @property
    def custom_types_available(self):
        return self.service.entry_types is not None

    def list_entry_types(self):
        result = self.service.entry_types.list_types() if self.custom_types_available else Result.success(())
        if result.ok:
            self._custom_types = result.value
        return result

    def list_work_modes(self):
        return self.service.work_modes.list_types() if self.service.work_modes is not None else Result.success(())

    def elapsed_hours(self):
        return max(0, timestamp_span_hours(self.timer.started_at, self.now())) if self.timer else 0

    @property
    def resume_due(self):
        return bool(self.timer and self.timer.break_until and self.now() >= self.timer.break_until)

    def get_entry(self, entry_id):
        return self.service.get_entry(entry_id)

    def discard_timer(self):
        result = self.service.discard_timer()
        if result.ok:
            self._share_idle_fields(completed=self.draft.original)
        return result

    def delete_entry(self, record):
        result = self.service.delete(record)
        if result.ok:
            if self.draft.original and self.draft.original.id == record.id:
                self.clear(self.draft.day)
            if self.auto_completed and self.auto_completed.id == record.id:
                self.auto_completed = None
                self.auto_content = ""
        return result

    def delete_event(self, event):
        return self.service.delete_event(event)

    def set_default_break_hours(self, hours: float) -> None:
        self.default_break_hours = max(0.0, min(float(hours), 4.0))

    @property
    def rewrite_available(self):
        return self._rewrite_handler is not None and bool(getattr(self._rewrite_handler, "available", True))

    def rewrite_content(self, content: str, cancellation_token=None):
        if not self.rewrite_available:
            return Result.failure(ValidationError("ai_rewrite_not_configured", "ai_rewrite_not_configured"))
        result = self._rewrite_handler.handle(RewriteTextCommand(self.service.user_id, content,
                                               context="time_entry", language=self._language), cancellation_token=cancellation_token)
        if not result.ok:
            return result
        if result.value is None:
            return Result.failure(ValidationError("time_entry_content_too_long", "time_entry_content_too_long"))
        try:
            return Result.success(require_entry_content(result.value.content))
        except ValueError:
            return Result.failure(ValidationError("time_entry_content_too_long", "time_entry_content_too_long"))

    @property
    def manual_dirty(self) -> bool:
        return self.draft != self._baseline and bool(self.draft.original or self.draft.start or self.draft.end or self.draft.content)

    @property
    def editing_active_timer(self):
        origin = getattr(self, "_timer_origin", None)
        return bool(self.service.timer and getattr(self, "_timer_shares_draft", False) and origin
            and self.draft.original is None
            and (self.draft.day, self.draft.start, self.draft.end, self.draft.entry_type,
                 self.draft.context, self.draft.work_mode) ==
            (origin.day, origin.start, origin.end, origin.entry_type, origin.context, origin.work_mode))

    @property
    def auto_dirty(self) -> bool:
        baseline = self.service.timer.content if self.service.timer else self.auto_completed.note if self.auto_completed else ""
        return (self.auto_content != baseline or (self.service.timer is None and self.auto_completed is not None
            and (self.auto_entry_type != self.auto_completed.entry_type.value or self.auto_context != self.auto_completed.context
                 or self.auto_work_mode != self.auto_completed.work_mode)))

    def new(self, day: date, *, start: str = "") -> None:
        self.draft = TimeEntryDraft(day, start=start, work_mode=self.service.default_work_mode())
        self._baseline = self.draft
        self._share_idle_fields(completed=None)

    def clear(self, day: date) -> None:
        self.new(day)

    def _share_idle_fields(self, *, completed=None):
        if self.service.timer is None:
            self.auto_content = self.draft.content
            if self._allows_automatic_recording(self.draft.entry_type):
                self.auto_completed = completed
                self.auto_entry_type = self.draft.entry_type
                self.auto_context = self.draft.context
                self.auto_work_mode = self.draft.work_mode
            else:
                self.auto_completed = None
                self.auto_entry_type = EntryType.NORMAL.value
                self.auto_context = WorkContext()
                self.auto_work_mode = self.service.default_work_mode()

    def _classification_category(self, value: str) -> EntryCategory | None:
        for record in (self.draft.original, self.auto_completed, self.timer):
            if record is not None and record.entry_type.value == value:
                return record.entry_type.category
        try:
            return EntryType(value).category
        except ValueError:
            if self._custom_types is None:
                self.list_entry_types()
            return next((definition.category for definition in self._custom_types or () if definition.value == value), None)

    def _allows_automatic_recording(self, value: str) -> bool:
        return self._classification_category(value) in (EntryCategory.WORK, EntryCategory.BREAK)

    def update_auto(self, *, content, entry_type, context,
                    work_mode: WorkModeValue | None | _Unset = _Unset.WORK_MODE):
        self.auto_content = content
        if self.editing_active_timer:
            self.draft = replace(self.draft, content=content)
        if self.service.timer is None:
            mode = self.auto_work_mode if isinstance(work_mode, _Unset) else work_mode
            if not self._allows_automatic_recording(entry_type):
                entry_type, context, mode = EntryType.NORMAL.value, WorkContext(), self.service.default_work_mode()
            elif self._classification_category(entry_type) == EntryCategory.BREAK:
                context, mode = WorkContext(), None
            self.auto_entry_type, self.auto_context = entry_type, context
            self.auto_work_mode = mode
            if not self._allows_automatic_recording(self.draft.entry_type):
                return
            if (self.auto_completed is not None and self.manual_dirty
                    and (self.draft.original is None or self.draft.original.id != self.auto_completed.id)):
                return
            self.update(start=self.draft.start, end=self.draft.end, entry_type=entry_type, content=content,
                        context=context, work_mode=mode)

    def discard_changes(self) -> None:
        self.draft = self._baseline
        self._share_idle_fields(completed=self.draft.original)
        timer = self.service.timer
        if timer:
            self._sync_auto()
        else:
            self.auto_content = self.auto_completed.note if self.auto_completed else self.draft.content

    def load(self, day: date):
        loaded = self.service.list_for_day(day)
        if self.changes_available:
            latest = self.service.latest_change()
            self.latest_change_info = latest.value if latest.ok else None
        if loaded.ok:
            self.entries = loaded.value
            if self.draft.day != day:
                self.new(day)
        return loaded

    def prepare_day_load(self, day: date):
        service = self.service.new_session(self.service.snapshot_state())
        def load():
            entries = service.list_for_day(day)
            if not entries.ok:
                return entries
            latest = service.latest_change() if service.changes_available else Result.success(None)
            return Result.success((entries.value, latest.value if latest.ok else None))
        return load

    def apply_day_records(self, records, latest_change):
        self.entries = records
        self.latest_change_info = latest_change

    def select(self, record: WorkLog) -> None:
        if self.service.timer is not None:
            self._timer_shares_draft = False
        self.draft = TimeEntryDraft(record.day, record.start_time or "", record.end_time or "",
                                    record.entry_type.value, record.note, original=record, context=record.context,
                                    work_mode=record.work_mode)
        self._baseline = self.draft
        self._share_idle_fields(completed=record)

    def update(self, *, start: str, end: str, entry_type: str, content: str, context: WorkContext | None = None,
               work_mode: WorkModeValue | None | _Unset = _Unset.WORK_MODE) -> None:
        linked = self.editing_active_timer
        mode = self.draft.work_mode if isinstance(work_mode, _Unset) else work_mode
        association = context if context is not None else self.draft.context
        if self._classification_category(entry_type) != EntryCategory.WORK:
            mode, association = None, WorkContext()
        self.draft = replace(self.draft, start=start, end=end, entry_type=entry_type, content=content,
                             context=association, work_mode=mode)
        self._share_idle_fields(completed=self.draft.original)
        if linked and self.editing_active_timer:
            self.auto_content = content

    def save_manual(self):
        draft = self.draft
        options = {"context": draft.context} if self.projects_available or draft.context != WorkContext() else {}
        saved = self.service.save_manual(draft.day, draft.start, draft.end, draft.entry_type, draft.content, draft.original,
                                        work_mode=draft.work_mode, **options)
        if saved.ok:
            self.select(saved.value)
        return saved

    def start(self, entry_type: str, content: str, *, now=None, break_entry=None,
              work_mode: WorkModeValue | None | _Unset = _Unset.WORK_MODE):
        original_draft = self.draft
        mode = self.auto_work_mode if isinstance(work_mode, _Unset) else work_mode
        shared = (original_draft.entry_type == entry_type and original_draft.content == content
                  and original_draft.context == self.auto_context and original_draft.work_mode == mode)
        options = {"context": self.auto_context} if self.projects_available else {}
        result = self.service.start(entry_type, content, now=now, break_entry=break_entry, work_mode=mode, **options)
        if result.ok:
            self._timer_shares_draft = shared
            if shared:
                timer = self.service.timer
                self.draft = TimeEntryDraft(timer.started_at.date(), timer.started_at.strftime("%H:%M"),
                    entry_type=timer.entry_type.value, content=timer.content, context=timer.context, work_mode=timer.work_mode)
                self._baseline = self.draft
            self._timer_origin = self.draft
            self.auto_completed = None
            self._sync_auto()
        return result

    def finish(self, *, now=None):
        linked = self.editing_active_timer
        result = self.service.finish(self.auto_content, now=now)
        if result.ok:
            self.auto_completed = result.value
            self.auto_content = result.value.note
            self.auto_entry_type = result.value.entry_type.value
            self.auto_context = result.value.context
            self.auto_work_mode = result.value.work_mode
            if (not self.manual_dirty and self._allows_automatic_recording(self.draft.entry_type)) or linked:
                self.select(result.value)
        return result

    def save_content(self):
        if self.service.timer is None and self.auto_completed is not None:
            original = self.auto_completed
            options = {"context": self.auto_context} if self.projects_available or self.auto_context != WorkContext() else {}
            result = self.service.save_manual(original.day, original.start_time or "", original.end_time or "",
                self.auto_entry_type, self.auto_content, original, work_mode=self.auto_work_mode, **options)
            if result.ok:
                record = result.value
                if self.draft.original is not None and self.draft.original.id == record.id:
                    self.draft = replace(self.draft, content=record.note, entry_type=record.entry_type.value,
                                         context=record.context, work_mode=record.work_mode, original=record)
                    self._baseline = TimeEntryDraft(record.day, record.start_time or "", record.end_time or "",
                        record.entry_type.value, record.note, record, record.context, record.work_mode)
                    self._share_idle_fields(completed=record)
                else:
                    if self.manual_dirty or not self._allows_automatic_recording(self.draft.entry_type):
                        self.auto_completed = record
                        self.auto_content, self.auto_entry_type, self.auto_context = record.note, record.entry_type.value, record.context
                        self.auto_work_mode = record.work_mode
                    else:
                        self.select(record)
            return result
        result = self.service.save_content(self.auto_content, self.auto_completed)
        if result.ok and self.editing_active_timer:
            self._baseline = self.draft
        if result.ok and self.service.timer is None:
            self.select(result.value)
        return result

    def take_break(self, *, now=None):
        result = self.service.take_break(self.default_break_hours, self.auto_content, now=now)
        if result.ok:
            self.select(result.value)
            self.auto_completed = None
            self.auto_entry_type = EntryType.NORMAL.value
            self.auto_context = WorkContext()
            self.auto_work_mode = self.service.default_work_mode()
        return result

    def advance(self, *, now=None):
        timer = self.service.timer
        if timer and timer.break_until and (now or self.service.now()) >= timer.break_until:
            result = self.service.resume(self.auto_content, at_deadline=True)
            if result.ok:
                self._sync_auto()
            return result
        return Result.success(None)

    def _sync_auto(self) -> None:
        if self.service.timer:
            self.auto_entry_type = self.service.timer.entry_type.value
            self.auto_content = self.service.timer.content
            self.auto_context = self.service.timer.context
            self.auto_work_mode = self.service.timer.work_mode
