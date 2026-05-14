"""Calendar query DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class GetCalendarEventsForDayQuery:
    user_id: int
    day: date


@dataclass(frozen=True)
class GetCalendarEventsForRangeQuery:
    user_id: int
    start_day: date
    end_day: date


@dataclass(frozen=True)
class GetHolidaysForRangeQuery:
    country: str
    start_day: date
    end_day: date
