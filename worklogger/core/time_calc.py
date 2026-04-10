"""Work-hour calculation utilities."""

from datetime import datetime


def calc_hours(start: str, end: str, break_hours: float | None) -> float:
    """Return worked hours (start→end minus break time). Returns 0.0 on error."""
    try:
        s = datetime.strptime(start, "%H:%M")
        e = datetime.strptime(end,   "%H:%M")
        return max((e - s).seconds / 3600 - float(break_hours or 0), 0.0)
    except Exception:
        return 0.0


def calc_overtime(hours: float, standard: float) -> float:
    return max(hours - standard, 0.0)


def detect_country() -> str:
    """Detect ISO country code from local timezone (lazy import)."""
    from config.constants import TZ_COUNTRY
    try:
        from tzlocal import get_localzone
        return TZ_COUNTRY.get(str(get_localzone()), "US")
    except Exception:
        return "US"
