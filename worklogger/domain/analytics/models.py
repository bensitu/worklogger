"""Analytics domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class MonthStats:
    total_hours: float
    overtime_hours: float
    work_days: int
    leave_days: int
    average_hours: float


@dataclass(frozen=True)
class ChartDataBundle:
    bar_data: tuple[tuple[str, float], ...]
    line_data: tuple[tuple[str, float], ...]
    leave_indices: frozenset[int]
    leave_line_data: tuple[float | None, ...]
    leave_hours_data: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class AnalyticsDashboard:
    period_start: date
    period_end: date
    stats: MonthStats
    previous_stats: MonthStats
    target_hours: float
    total_days: int
    previous_total_days: int
    trend: ChartDataBundle
    average: ChartDataBundle
    work_modes: tuple[tuple[str, float], ...]
    daily_average_trend: ChartDataBundle
