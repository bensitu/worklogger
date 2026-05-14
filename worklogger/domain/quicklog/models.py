"""Quick log domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class QuickLog:
    id: int | None
    user_id: int
    day: date
    description: str
    start_time: str = ""
    end_time: str = ""
    created_at: datetime | None = None

