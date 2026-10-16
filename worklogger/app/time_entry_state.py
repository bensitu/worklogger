"""Explicit state transferred between recording service sessions."""

from dataclasses import dataclass

from worklogger.domain.shared.errors import AppError
from worklogger.domain.worklog.timer_state import EntryTimer


@dataclass(frozen=True)
class RecordingState:
    timer: EntryTimer | None = None
    persisted_timer: str | None = None
    restore_failed: bool = False
    error: AppError | None = None
