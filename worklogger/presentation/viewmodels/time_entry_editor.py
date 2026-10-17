"""Immutable display state shared by record editor rendering and actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from worklogger.domain.projects.models import WorkContext
from worklogger.domain.worklog.models import CustomEntryType, WorkLog, EntryType, WorkMode
from worklogger.domain.worklog.timer_state import EntryTimer

if TYPE_CHECKING:
    from worklogger.presentation.viewmodels.time_entries import TimeEntryDraft, TimeEntryViewModel


@dataclass(frozen=True)
class TimeEntryEditorState:
    draft: TimeEntryDraft
    active_timer: EntryTimer | None
    selected_record: WorkLog | None
    linked_timer: bool
    entry_type: str
    type_snapshot: EntryType | CustomEntryType | None
    content: str
    context: WorkContext
    historical_break_hours: float
    save_action: Literal["new", "changes", "content"]
    can_save: bool
    work_mode: WorkMode | None = None

    @property
    def processing_target(self) -> tuple[str, object]:
        if self.active_timer is not None:
            return "timer", self.active_timer.capture_id
        if self.selected_record is not None:
            return "entry", self.selected_record.id
        return "draft", self.draft.day


def editor_state(model: TimeEntryViewModel, *, automatic: bool) -> TimeEntryEditorState:
    draft = model.draft
    linked_timer = model.editing_active_timer
    active_timer = model.timer if automatic or linked_timer else None
    selected = model.auto_completed if automatic and model.timer is None else draft.original if not automatic else None
    snapshot = active_timer.entry_type if active_timer else selected.entry_type if selected else None
    if active_timer is not None:
        save_action = "content"
    elif selected is not None:
        save_action = "changes"
    else:
        save_action = "new"
    can_save = (model.auto_dirty and bool(model.timer or model.auto_completed) if automatic
                else model.auto_dirty if linked_timer else model.manual_dirty)
    return TimeEntryEditorState(
        draft=draft, active_timer=active_timer, selected_record=selected, linked_timer=linked_timer,
        entry_type=model.auto_entry_type if automatic else draft.entry_type,
        type_snapshot=snapshot, content=model.auto_content if automatic else draft.content,
        context=active_timer.context if active_timer else model.auto_context if automatic else draft.context,
        work_mode=active_timer.work_mode if active_timer else model.auto_work_mode if automatic else draft.work_mode,
        historical_break_hours=draft.original.break_hours if not automatic and draft.original else 0,
        save_action=save_action, can_save=can_save,
    )
