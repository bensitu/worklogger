"""Calendar arithmetic and clock-time labels shared by workflows."""

from datetime import date


def add_months(day: date, months: int) -> date:
    """Return the first day of the month at the given offset."""
    month_index = day.year * 12 + day.month - 1 + months
    return date(month_index // 12, month_index % 12 + 1, 1)


def time_range_label(start_time: str | None, end_time: str | None) -> str:
    start = str(start_time or "").strip()
    end = str(end_time or "").strip()
    return f"{start}-{end}" if start and end else start or end
