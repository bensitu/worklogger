"""Localized date labels shared by calendar and reporting surfaces."""

from datetime import date
import math

from worklogger.infrastructure.i18n import _


def month_name(day: date) -> str:
    return (
        _("January"), _("February"), _("March"), _("April"), _("May"), _("June"),
        _("July"), _("August"), _("September"), _("October"), _("November"), _("December"),
    )[day.month - 1]


def month_label(day: date) -> str:
    return _("{month} {year}").format(month=month_name(day), year=day.year)


def day_label(day: date) -> str:
    return _("{month} {day}, {year}").format(month=month_name(day), day=day.day, year=day.year)


def period_range_label(start: date, end: date) -> str:
    if start == end:
        return day_label(start)
    if start.year == end.year:
        return _("{start_month} {start_day} - {end_month} {end_day}, {year}").format(
            start_month=month_name(start), start_day=start.day,
            end_month=month_name(end), end_day=end.day, year=end.year,
        )
    return _("{start} - {end}").format(start=day_label(start), end=day_label(end))


def duration_label(hours: float) -> str:
    if not math.isfinite(hours):
        return "-"
    minutes = round(abs(hours) * 60)
    label = _("{hours}h {minutes}m").format(hours=minutes // 60, minutes=minutes % 60)
    return "-" + label if hours < 0 and minutes else label


def report_period_label(report_type: str, start: date, end: date) -> str:
    label = period_range_label(start, end)
    if report_type == "weekly":
        label += " " + _("(Week {week})").format(week=start.isocalendar().week)
    return label
