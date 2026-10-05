"""Report period rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from calendar import monthrange


REPORT_TYPES = frozenset({"daily", "weekly", "monthly"})


@dataclass(frozen=True)
class ReportPeriod:
    report_type: str
    start: date
    end: date


def normalize_report_type(report_type: str) -> str:
    if not isinstance(report_type, str):
        raise TypeError("report_type_must_be_string")
    normalized = report_type.strip().lower()
    if normalized not in REPORT_TYPES:
        raise ValueError("invalid_report_type")
    return normalized


def weekly_period(selected_day: date, week_start_monday: bool = False) -> ReportPeriod:
    offset = selected_day.weekday() if week_start_monday else (selected_day.weekday() + 1) % 7
    start = selected_day - timedelta(days=offset)
    return ReportPeriod("weekly", start, start + timedelta(days=6))


def daily_period(selected_day: date) -> ReportPeriod:
    return ReportPeriod("daily", selected_day, selected_day)


def monthly_period(year: int, month: int) -> ReportPeriod:
    if not 1 <= int(month) <= 12:
        raise ValueError("invalid_month")
    _, days = monthrange(int(year), int(month))
    return ReportPeriod(
        "monthly",
        date(int(year), int(month), 1),
        date(int(year), int(month), days),
    )


def validate_report_period(report_type: str, start: date, end: date) -> ReportPeriod:
    normalized = normalize_report_type(report_type)
    if end < start:
        raise ValueError("report_period_invalid")
    if normalized == "daily" and start != end:
        raise ValueError("report_period_invalid")
    if normalized == "weekly" and ((end - start).days != 6 or start.weekday() not in {0, 6}):
        raise ValueError("report_period_invalid")
    if normalized == "monthly" and (start.day != 1 or end != monthly_period(start.year, start.month).end):
        raise ValueError("report_period_invalid")
    return ReportPeriod(normalized, start, end)
