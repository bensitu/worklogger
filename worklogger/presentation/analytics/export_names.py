"""Readable, locale-independent names for period-scoped analytics exports."""

from datetime import date, datetime

from worklogger.domain.analytics.rules import analytics_period

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def analytics_export_filename(scope: str, day: date, kind: str, *, exported_at: datetime | None = None) -> str:
    start, _end = analytics_period(day.year, day.month, scope)
    if kind not in {"csv", "pdf"}:
        raise ValueError("analytics_export_format_invalid")
    period = (f"{start.year}{_MONTHS[start.month - 1]}" if scope == "monthly" else
              f"{start.year}Q{(start.month - 1) // 3 + 1}" if scope == "quarterly" else str(start.year))
    timestamp = (exported_at or datetime.now().astimezone()).strftime("%Y%m%d-%H%M%S-%f")[:-3]
    return f"analytics-{scope}-{period}-{timestamp}.{kind}"
