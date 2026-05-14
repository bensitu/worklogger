"""Quick log command DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class AddQuickLogCommand:
    user_id: int
    day: date
    description: str
    start_time: str = ""
    end_time: str = ""


@dataclass(frozen=True)
class UpdateQuickLogCommand:
    user_id: int
    quick_log_id: int
    day: date
    description: str
    start_time: str = ""
    end_time: str = ""


@dataclass(frozen=True)
class DeleteQuickLogCommand:
    user_id: int
    quick_log_id: int
