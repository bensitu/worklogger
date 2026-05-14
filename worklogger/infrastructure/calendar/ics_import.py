"""iCalendar import adapter."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import re

from worklogger.config.constants import ICS_MAX_BYTES
from worklogger.domain.calendar.models import CalendarEvent
from worklogger.domain.shared.errors import InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result


class IcsCalendarImporter:
    def __init__(self, *, max_bytes: int = ICS_MAX_BYTES) -> None:
        self._max_bytes = int(max_bytes)

    def read_events(
        self,
        source: Path,
        *,
        user_id: int,
    ) -> Result[tuple[CalendarEvent, ...]]:
        source = Path(source)
        try:
            if source.stat().st_size > self._max_bytes:
                return Result.failure(
                    ValidationError("ics_file_too_large", "ics_file_too_large")
                )
            raw = source.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return Result.failure(
                InfrastructureError(
                    "ics_read_failed",
                    "ics_read_failed",
                    {"reason": str(exc)},
                )
            )
        return Result.success(_parse_ics(raw, user_id=user_id, source=str(source)))


def _parse_ics(raw: str, *, user_id: int, source: str) -> tuple[CalendarEvent, ...]:
    unfolded = re.sub(r"\r?\n[ \t]", "", raw)
    events: list[CalendarEvent] = []
    for block in re.split(r"BEGIN:VEVENT", unfolded, flags=re.IGNORECASE)[1:]:
        end = re.search(r"END:VEVENT", block, re.IGNORECASE)
        if end:
            block = block[: end.start()]
        properties = _properties(block)
        summary = _unescape(properties.get("SUMMARY", ("", ""))[1]).strip()
        if not summary:
            continue
        start, all_day = _parse_dt(*properties.get("DTSTART", ("", "")))
        end_dt, _end_all_day = _parse_dt(*properties.get("DTEND", ("", "")))
        if start is None:
            continue
        day = start if isinstance(start, date) and not isinstance(start, datetime) else start.date()
        events.append(
            CalendarEvent(
                id=None,
                user_id=user_id,
                day=day,
                summary=summary,
                start_time=None if all_day else _time_text(start),
                end_time=None if all_day else _time_text(end_dt),
                description=_unescape(properties.get("DESCRIPTION", ("", ""))[1]),
                location=_unescape(properties.get("LOCATION", ("", ""))[1]),
                all_day=all_day,
                source_file=source,
            )
        )
    return tuple(events)


def _properties(block: str) -> dict[str, tuple[str, str]]:
    properties: dict[str, tuple[str, str]] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key_part, _separator, value = line.partition(":")
        parts = key_part.split(";")
        key = parts[0].strip().upper()
        params = ";".join(part.strip().upper() for part in parts[1:])
        properties[key] = (params, value.strip())
    return properties


def _parse_dt(params: str, value: str) -> tuple[datetime | date | None, bool]:
    cleaned = re.sub(r"Z$", "", value.strip())
    all_day = "VALUE=DATE" in params or ("T" not in cleaned and len(cleaned) >= 8)
    if all_day:
        try:
            return datetime.strptime(cleaned[:8], "%Y%m%d").date(), True
        except ValueError:
            return None, False
    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M"):
        try:
            return datetime.strptime(cleaned, fmt), False
        except ValueError:
            pass
    return None, False


def _time_text(value: datetime | date | None) -> str | None:
    if not isinstance(value, datetime):
        return None
    return value.strftime("%H:%M")


def _unescape(value: str) -> str:
    return (
        value.replace("\\n", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
    )
