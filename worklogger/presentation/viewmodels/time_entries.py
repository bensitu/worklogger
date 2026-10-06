"""Presentation state for manual and automatic time-entry editing."""

from dataclasses import dataclass, replace
from datetime import date

from worklogger.app.use_cases.time_entries import TimeEntryService
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkLog


@dataclass(frozen=True)
class TimeEntryDraft:
    day: date
    start: str = ""
    end: str = ""
    work_type: str = "normal"
    content: str = ""
    original: WorkLog | None = None


class TimeEntryViewModel:
    def __init__(self, service: TimeEntryService, *, default_break_hours: float = 1) -> None:
        self.service = service
        self.default_break_hours = default_break_hours
        self.draft = TimeEntryDraft(service.now().date())
        self._baseline = self.draft
        self.entries = ()
        self.auto_completed: WorkLog | None = None
        self.auto_content = service.timer.content if service.timer else ""
        self.auto_work_type = service.timer.work_type.value if service.timer else "normal"

    @property
    def manual_dirty(self) -> bool:
        return self.draft != self._baseline and bool(self.draft.original or self.draft.start or self.draft.end or self.draft.content)

    @property
    def auto_dirty(self) -> bool:
        baseline = self.service.timer.content if self.service.timer else self.auto_completed.note if self.auto_completed else ""
        return self.auto_content != baseline

    def new(self, day: date, *, start: str = "") -> None:
        self.draft = TimeEntryDraft(day, start=start, work_type=self.draft.work_type)
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
        if loaded.ok:
            self.entries = loaded.value
            if self.draft.day != day:
                self.new(day)
        return loaded

    def select(self, record: WorkLog) -> None:
        self.draft = TimeEntryDraft(record.day, record.start_time or "", record.end_time or "",
                                    record.work_type.value, record.note, original=record)
        self._baseline = self.draft

    def update(self, *, start: str, end: str, work_type: str, content: str) -> None:
        self.draft = replace(self.draft, start=start, end=end, work_type=work_type, content=content)

    def save_manual(self):
        draft = self.draft
        saved = self.service.save_manual(draft.day, draft.start, draft.end, draft.work_type, draft.content, draft.original)
        if saved.ok:
            if self.auto_completed and self.auto_completed.id == saved.value.id:
                self.auto_completed = saved.value
                self.auto_content = saved.value.note
            self.new(saved.value.day, start=saved.value.end_time or "")
        return saved

    def start(self, work_type: str, content: str, *, now=None):
        result = self.service.start(work_type, content, now=now)
        if result.ok:
            self.auto_completed = None
            self._sync_auto()
        return result

    def finish(self, *, now=None):
        result = self.service.finish(self.auto_content, now=now)
        if result.ok:
            self.auto_completed = result.value
            self.auto_content = result.value.note
        return result

    def save_content(self):
        result = self.service.save_content(self.auto_content, self.auto_completed)
        if result.ok and self.service.timer is None:
            self.auto_completed = result.value
        return result

    def take_break(self, *, now=None):
        if self.service.timer and self.service.timer.break_until:
            result = self.service.resume(self.auto_content, now=now)
        else:
            result = self.service.take_break(self.default_break_hours, self.auto_content, now=now)
        if result.ok:
            self._sync_auto()
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
