"""Report period rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from calendar import monthrange

from worklogger.domain.shared.dates import add_months


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
    try:
        start = selected_day - timedelta(days=offset)
        return ReportPeriod("weekly", start, start + timedelta(days=6))
    except OverflowError:
        raise ValueError("report_period_invalid") from None


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


def period_for_day(report_type: str, selected_day: date, week_start_monday: bool = False) -> ReportPeriod:
    normalized = normalize_report_type(report_type)
    if type(selected_day) is not date:
        raise ValueError("report_period_invalid")
    if normalized == "daily":
        return daily_period(selected_day)
    if normalized == "weekly":
        return weekly_period(selected_day, week_start_monday)
    return monthly_period(selected_day.year, selected_day.month)


def shift_report_period(day: date, report_type: str, direction: int) -> date:
    report_type = normalize_report_type(report_type)
    if type(day) is not date or type(direction) is not int:
        raise ValueError("report_period_invalid")
    try:
        if report_type == "daily":
            return day + timedelta(days=direction)
        if report_type == "weekly":
            return day + timedelta(days=direction * 7)
        shifted = add_months(day, direction)
        return shifted.replace(day=min(day.day, monthrange(shifted.year, shifted.month)[1]))
    except (OverflowError, ValueError):
        raise ValueError("report_period_invalid") from None


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
