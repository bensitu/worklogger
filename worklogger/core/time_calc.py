"""Work-hour calculation utilities."""

from datetime import datetime, timedelta
from config.constants import MAX_SHIFT_HOURS


def _parse_minutes(hhmm: str) -> int | None:
    try:
        h, m = hhmm.split(":")
        hh = int(h)
        mm = int(m)
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return hh * 60 + mm
    except Exception:
        return None
    return None


def calc_shift_span_hours(
    start: str,
    end: str,
    *,
    max_shift_hours: float = MAX_SHIFT_HOURS,
) -> float | None:
    """Return raw shift span hours, supporting overnight shifts.

    Returns None when input is invalid or exceeds max_shift_hours.
    """
    s_min = _parse_minutes(start)
    e_min = _parse_minutes(end)
    if s_min is None or e_min is None:
        return None

    delta_min = e_min - s_min
    if delta_min <= 0:
        # end at/before start => next-day checkout (overnight)
        delta_min += 24 * 60

    span_h = delta_min / 60.0
    if span_h <= 0 or span_h > float(max_shift_hours):
        return None
    return span_h


def is_overnight_shift(start: str, end: str) -> bool:
    s_min = _parse_minutes(start)
    e_min = _parse_minutes(end)
    if s_min is None or e_min is None:
        return False
    return e_min <= s_min


def shift_datetimes(date_iso: str, start: str, end: str) -> tuple[datetime, datetime] | None:
    """Return date-aware (start_dt, end_dt); end_dt may be next day."""
    try:
        start_dt = datetime.strptime(f"{date_iso} {start}", "%Y-%m-%d %H:%M")
        end_dt = datetime.strptime(f"{date_iso} {end}", "%Y-%m-%d %H:%M")
    except Exception:
        return None
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)
    return start_dt, end_dt


def calc_hours(start: str, end: str, break_hours: float | None) -> float:
    """Return worked hours (start→end minus break), supports overnight."""
    try:
        span_h = calc_shift_span_hours(start, end)
        if span_h is None:
            return 0.0
        br = float(break_hours or 0)
        if br < 0 or br >= span_h:
            return 0.0
        return max(span_h - br, 0.0)
    except Exception:
        return 0.0


def detect_country() -> str:
    """Detect ISO country code from local timezone (lazy import)."""
    from config.constants import TZ_COUNTRY
    try:
        from tzlocal import get_localzone
        return TZ_COUNTRY.get(str(get_localzone()), "US")
    except Exception:
        return "US"
