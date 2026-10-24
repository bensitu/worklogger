"""Work log query DTOs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GetMonthRecordsQuery:
    user_id: int
    year: int
    month: int


@dataclass(frozen=True)
class GetAllWorkLogsQuery:
    user_id: int
