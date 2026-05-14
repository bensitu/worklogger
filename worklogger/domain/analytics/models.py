"""Analytics domain models."""

from __future__ import annotations

from dataclasses import dataclass


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
