"""Presentation state for manual and automatic time-entry editing."""

from dataclasses import dataclass, replace
from datetime import date

from worklogger.app.ports import TimeEntryOperations
from worklogger.app.commands.ai_commands import RewriteTextCommand
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkLog
from worklogger.domain.projects.models import WorkContext
from worklogger.domain.worklog.rules import timestamp_span_hours
from worklogger.domain.worklog.editing import merge_entries
from worklogger.domain.worklog.reminders import timer_reminders


@dataclass(frozen=True)
class TimeEntryDraft:
    day: date
    start: str = ""
    end: str = ""
    work_type: str = "normal"
    content: str = ""
    original: WorkLog | None = None
    context: WorkContext = WorkContext()


class TimeEntryViewModel:
    def __init__(self, service: TimeEntryOperations, *, default_break_hours: float = 1,
                 rewrite_handler=None, language="en_US") -> None:
        self.service = service
        self._rewrite_handler, self._language = rewrite_handler, language
        self.default_break_hours = default_break_hours
        self.draft = TimeEntryDraft(service.now().date())
        self._baseline = self.draft
        self.entries = ()
        self.auto_completed: WorkLog | None = None
        self.auto_content = service.timer.content if service.timer else ""
        self.auto_work_type = service.timer.work_type.value if service.timer else "normal"
        self.auto_context = service.timer.context if service.timer else WorkContext()
        self.latest_change_info = None
        self.timer_reminder_hours = 10.0
        self.continuous_timer_reminder_hours = 0.0

    def set_timer_reminders(self, long_hours, continuous_hours):
        self.timer_reminder_hours = long_hours
        self.continuous_timer_reminder_hours = continuous_hours

    def reminder_reasons(self):
        timer = self.timer
        return timer_reminders(timer.started_at, self.now(), timer.work_type, long_hours=self.timer_reminder_hours,
                               continuous_hours=self.continuous_timer_reminder_hours) if timer else ()

    @property
    def projects_available(self):
        return getattr(self.service, "projects", None) is not None

    def project_inventory(self):
        if not self.projects_available:
            return Result.success(((), {}))
        return self.service.projects.catalog()

    def recent_contexts(self):
        return self.service.projects.recent_contexts() if self.projects_available else Result.success(())

    def associate(self, records, context):
        return self.service.associate(records, context)

    @property
    def search_available(self):
        return bool(getattr(self.service, "search_available", False))

    def search(self, criteria, *, cursor=None):
        return self.service.search(criteria, cursor=cursor)

    @property
    def changes_available(self):
        return bool(getattr(self.service, "changes_available", False))

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
        return getattr(self.service, "work_types", None) is not None

    def list_work_types(self):
        return self.service.work_types.list_types() if self.custom_types_available else Result.success(())

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
            self.auto_content = ""
            self.auto_completed = None
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

    def rewrite_content(self, content: str):
        if not self.rewrite_available:
            return Result.failure(ValidationError("ai_rewrite_not_configured", "ai_rewrite_not_configured"))
        result = self._rewrite_handler.handle(RewriteTextCommand(self.service.user_id, content,
                                               context="time_entry", language=self._language))
        if not result.ok:
            return result
        if result.value is None or len(result.value.content) > 16000:
            return Result.failure(ValidationError("time_entry_content_too_long", "time_entry_content_too_long"))
        return Result.success(result.value.content)

    @property
    def manual_dirty(self) -> bool:
        return self.draft != self._baseline and bool(self.draft.original or self.draft.start or self.draft.end or self.draft.content)

    @property
    def auto_dirty(self) -> bool:
        baseline = self.service.timer.content if self.service.timer else self.auto_completed.note if self.auto_completed else ""
        return self.auto_content != baseline

    def new(self, day: date, *, start: str = "") -> None:
        self.draft = TimeEntryDraft(day, start=start)
        self._baseline = self.draft

    def clear(self, day: date) -> None:
        self.draft = TimeEntryDraft(day)
        self._baseline = self.draft

    def discard_changes(self) -> None:
        self.draft = self._baseline
        timer = self.service.timer
        self.auto_content = timer.content if timer else self.auto_completed.note if self.auto_completed else ""

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

    def select(self, record: WorkLog) -> None:
        self.draft = TimeEntryDraft(record.day, record.start_time or "", record.end_time or "",
                                    record.work_type.value, record.note, original=record, context=record.context)
        self._baseline = self.draft

    def update(self, *, start: str, end: str, work_type: str, content: str, context: WorkContext | None = None) -> None:
        self.draft = replace(self.draft, start=start, end=end, work_type=work_type, content=content,
                             context=context if context is not None else self.draft.context)

    def save_manual(self):
        draft = self.draft
        options = {"context": draft.context} if self.projects_available or draft.context != WorkContext() else {}
        saved = self.service.save_manual(draft.day, draft.start, draft.end, draft.work_type, draft.content, draft.original, **options)
        if saved.ok:
            if self.auto_completed and self.auto_completed.id == saved.value.id:
                self.auto_completed = saved.value
                self.auto_content = saved.value.note
            self.new(saved.value.day, start=saved.value.end_time or "")
        return saved

    def start(self, work_type: str, content: str, *, now=None, break_entry=None):
        options = {"context": self.auto_context} if self.projects_available else {}
        result = self.service.start(work_type, content, now=now, break_entry=break_entry, **options)
        if result.ok:
            self.auto_completed = None
            self._sync_auto()
        return result

    def finish(self, *, now=None):
        result = self.service.finish(self.auto_content, now=now)
        if result.ok:
            self.auto_completed = result.value
            self.auto_content = result.value.note
            self.auto_work_type = "normal"
            self.auto_context = WorkContext()
        return result

    def save_content(self):
        result = self.service.save_content(self.auto_content, self.auto_completed)
        if result.ok and self.service.timer is None:
            self.auto_completed = result.value
        return result

    def take_break(self, *, now=None):
        result = self.service.take_break(self.default_break_hours, self.auto_content, now=now)
        if result.ok:
            self.auto_completed = result.value
            self.auto_content = result.value.note
            self.auto_work_type = "normal"
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
            self.auto_work_type = self.service.timer.work_type.value
            self.auto_content = self.service.timer.content
            self.auto_context = self.service.timer.context
