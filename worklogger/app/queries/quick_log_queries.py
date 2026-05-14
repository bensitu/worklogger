"""Quick log query DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class GetQuickLogsForDayQuery:
    user_id: int
    day: date


@dataclass(frozen=True)
class GetQuickLogsForRangeQuery:
    user_id: int
    start_day: date
    end_day: date

