"""Calendar domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Holiday:
    day: date
    name: str


@dataclass(frozen=True)
class CalendarEvent:
    id: int | None
    user_id: int
    day: date
    summary: str
    start_time: str | None = None
    end_time: str | None = None
    description: str = ""
    location: str = ""
    all_day: bool = False
    source_file: str = ""
