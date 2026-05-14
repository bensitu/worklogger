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


def weekly_period(selected_day: date) -> ReportPeriod:
    start = selected_day - timedelta(days=selected_day.weekday())
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
    return ReportPeriod(normalized, start, end)
