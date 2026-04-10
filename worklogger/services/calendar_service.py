"""Calendar service: ICS parsing with time info for AI context generation."""

from __future__ import annotations
import re
from datetime import datetime, date, timedelta


def parse_ics_rich(filepath: str) -> list[dict]:
    """Parse an ICS file and return a rich list of event dicts.

    Each event contains:
      ``date``        – ``datetime.date``
      ``start``       – ``datetime`` or ``None``
      ``end``         – ``datetime`` or ``None``
      ``summary``     – str
      ``description`` – str
      ``location``    – str
      ``all_day``     – bool
    """
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
    except Exception:
        return []

    # RFC 5545 allows folded continuation lines in .ics files.
    raw = re.sub(r"\r?\n[ \t]", "", raw)

    events: list[dict] = []
    for block in re.split(r"BEGIN:VEVENT", raw, flags=re.IGNORECASE)[1:]:
        end = re.search(r"END:VEVENT", block, re.IGNORECASE)
        if end:
            block = block[: end.start()]

        props: dict[str, str] = {}
        for line in block.splitlines():
            if ":" not in line:
                continue
            key_part, _, value = line.partition(":")
            key = key_part.split(";")[0].strip().upper()
            props[key] = value.strip()

        dtstart_raw = props.get("DTSTART", "")
        dtend_raw = props.get("DTEND",   "")
        summary = _unescape(props.get("SUMMARY",     ""))
        description = _unescape(props.get("DESCRIPTION", ""))
        location = _unescape(props.get("LOCATION",    ""))

        if not summary:
            continue

        start, all_day = _parse_dt(dtstart_raw)
        end_dt, _ = _parse_dt(dtend_raw)

        if start is None:
            continue

        events.append(
            dict(
                date=start.date() if isinstance(start, datetime) else start,
                start=start if not all_day else None,
                end=end_dt if not all_day else None,
                summary=summary,
                description=description,
                location=location,
                all_day=all_day,
            )
        )

    return events


def _parse_dt(value: str) -> tuple[datetime | date | None, bool]:
    """Return ``(dt, all_day)``."""
    value = re.sub(r"Z$", "", value.strip())
    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M"):
        try:
            return datetime.strptime(value, fmt), False
        except ValueError:
            pass
    try:
        return datetime.strptime(value[:8], "%Y%m%d").date(), True
    except ValueError:
        pass
    return None, False


def _unescape(v: str) -> str:
    return (v.replace("\\n", "\n")
             .replace("\\,", ",")
             .replace("\\;", ";")
             .replace("\\\\", "\\"))


def get_day_events(events: list[dict], target: date) -> list[dict]:
    return [e for e in events if e["date"] == target]


def get_week_events(events: list[dict], monday: date) -> list[dict]:
    sunday = monday + timedelta(days=6)
    return [e for e in events if monday <= e["date"] <= sunday]


def get_month_events(events: list[dict], year: int, month: int) -> list[dict]:
    return [e for e in events if e["date"].year == year and e["date"].month == month]


def format_events_for_ai(events: list[dict]) -> str:
    """Render events as a plain-text bullet list suitable for AI context."""
    if not events:
        return "(none)"
    lines: list[str] = []
    for ev in sorted(events, key=lambda e: (e["date"], e["start"] or datetime.min)):
        parts: list[str] = []
        if ev["start"]:
            t = ev["start"].strftime("%H:%M")
            if ev["end"]:
                t += f"–{ev['end'].strftime('%H:%M')}"
            parts.append(t)
        parts.append(ev["summary"])
        if ev["location"]:
            parts.append(f"[{ev['location']}]")
        lines.append("- " + "  ".join(parts))
    return "\n".join(lines)
