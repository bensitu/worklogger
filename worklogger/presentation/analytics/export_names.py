"""Readable, locale-independent names for period-scoped analytics exports."""

from datetime import date

from worklogger.domain.analytics.rules import analytics_period

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def analytics_export_filename(scope: str, day: date, kind: str, *,
                              period: tuple[date, date] | None = None) -> str:
    start, end = period or analytics_period(day.year, day.month, scope)
    if kind not in {"csv", "pdf"}:
        raise ValueError("analytics_export_format_invalid")
    period_token = (f"{start.year}{_MONTHS[start.month - 1]}" if scope == "monthly" else
              f"{start.year}Q{(start.month - 1) // 3 + 1}" if scope == "quarterly" and end.month - start.month < 3
              else str(start.year))
    return f"analytics-{scope}-{period_token}.{kind}"
