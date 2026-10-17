"""Work log command DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from worklogger.domain.worklog.models import WorkMode


@dataclass(frozen=True)
class SaveWorkLogCommand:
    user_id: int
    day: date
    start_time: str | None
    end_time: str | None
    break_hours: float
    note: str
    entry_type: str
    expected_note: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    work_mode: WorkMode | None = None
