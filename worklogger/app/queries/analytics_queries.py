"""Analytics query DTOs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GetAnalyticsBundleQuery:
    user_id: int
    year: int
    month: int | None
    metric: str
    include_leaves: bool
    scope: str = "monthly"
    standard_leave_hours: float = 8.0


@dataclass(frozen=True)
class GetAnalyticsDashboardQuery:
    user_id: int
    year: int
    month: int
    scope: str = "monthly"
