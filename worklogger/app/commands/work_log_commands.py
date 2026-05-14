"""Work log command DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class SaveWorkLogCommand:
    user_id: int
    day: date
    start_time: str | None
    end_time: str | None
    break_hours: float
    note: str
    work_type: str


@dataclass(frozen=True)
class DeleteWorkLogCommand:
    user_id: int
    day: date

