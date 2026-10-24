"""Analytics domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from worklogger.domain.worklog.models import CustomEntryType, EntryType, WorkModeValue, WorkLog


@dataclass(frozen=True)
class MonthStats:
    total_hours: float
    overtime_hours: float
    work_days: int
    leave_days: int
    average_hours: float
    rest_days: int = 0


@dataclass(frozen=True)
class ChartDataBundle:
    bar_data: tuple[tuple[str, float], ...]
    line_data: tuple[tuple[str, float], ...]
    leave_indices: frozenset[int]
    leave_line_data: tuple[float | None, ...]
    leave_hours_data: tuple[tuple[str, float], ...]
    periods: tuple[tuple[date, date], ...] = ()


@dataclass(frozen=True)
class AnalyticsDashboard:
    period_start: date
    period_end: date
    stats: MonthStats
    previous_stats: MonthStats
    target_hours: float | None
    total_days: int
    previous_total_days: int
    trend: ChartDataBundle
    average: ChartDataBundle
    entry_types: tuple[tuple[EntryType | CustomEntryType, float], ...]
    daily_average_trend: ChartDataBundle
    planned_work_days: float | None = 0.0
    target_mode: str = "manual"
    planning_error: str = ""
    work_modes: tuple[tuple[WorkModeValue | None, float], ...] = ()
    records: tuple[WorkLog, ...] = ()
    standard_work_hours: float = 8.0
