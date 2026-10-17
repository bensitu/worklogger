"""Immutable record-editor requests and background operation results."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Generic, TYPE_CHECKING, TypeVar

from worklogger.app.recording_ports import TimeEntryOperations
from worklogger.app.time_entry_state import RecordingState
from worklogger.domain.projects.models import WorkContext
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.editing import EntryChangeInfo
from worklogger.domain.worklog.models import CustomEntryType, WorkLog, WorkMode

if TYPE_CHECKING:
    from worklogger.presentation.viewmodels.time_entries import TimeEntryViewModel

T = TypeVar("T")


@dataclass(frozen=True)
class TimeEntryDraft:
    day: date
    start: str = ""
    end: str = ""
    entry_type: str = "normal"
    content: str = ""
    original: WorkLog | None = None
    context: WorkContext = WorkContext()
    work_mode: WorkMode | None = None


@dataclass(frozen=True)
class TimeEntryEditState:
    draft: TimeEntryDraft
    baseline: TimeEntryDraft
    entries: tuple[WorkLog, ...] = ()
    auto_completed: WorkLog | None = None
    auto_content: str = ""
    auto_entry_type: str = "normal"
    auto_context: WorkContext = WorkContext()
    latest_change: EntryChangeInfo | None = None
    timer_origin: TimeEntryDraft | None = None
    timer_shares_draft: bool = False
    auto_work_mode: WorkMode | None = None
    custom_types: tuple[CustomEntryType, ...] | None = None


@dataclass(frozen=True)
class TimeEntryOperationResult(Generic[T]):
    outcome: Result[T]
    editor: TimeEntryEditState
    recording: RecordingState


@dataclass(frozen=True)
class TimeEntryOperationRequest:
    editor: TimeEntryEditState
    default_break_hours: float

    def execute(
        self, service: TimeEntryOperations, operation: Callable[[TimeEntryViewModel], Result[T]],
    ) -> Result[TimeEntryOperationResult[T]]:
        from worklogger.presentation.viewmodels.time_entries import TimeEntryViewModel

        model = TimeEntryViewModel(service, default_break_hours=self.default_break_hours,
                                   initial_state=self.editor)
        outcome = operation(model)
        return Result.success(TimeEntryOperationResult(outcome, model.snapshot_state(), service.snapshot_state()))
