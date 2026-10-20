"""Bounded iCalendar imports with local-time conversion and recurrence support."""

from __future__ import annotations

from datetime import datetime, time, timedelta, tzinfo
from pathlib import Path

from icalendar import Calendar
import recurring_ical_events
from tzlocal import get_localzone

from worklogger.config.constants import ICS_MAX_BYTES
from worklogger.domain.calendar.models import CalendarEvent
from worklogger.domain.shared.errors import InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.calendar.recurrence import prepare_recurrence_calendar


class IcsCalendarImporter:
    def __init__(self, *, max_bytes: int = ICS_MAX_BYTES, max_events: int = 10_000,
                 local_timezone: tzinfo | None = None) -> None:
        self._max_bytes = int(max_bytes)
        self._max_events = int(max_events)
        self._timezone = local_timezone

    def read_events(self, source: Path, *, user_id: int) -> Result[tuple[CalendarEvent, ...]]:
        try:
            with Path(source).open("rb") as handle:
                raw = handle.read(self._max_bytes + 1)
        except OSError:
            return Result.failure(InfrastructureError("ics_read_failed", "ics_read_failed"))
        if len(raw) > self._max_bytes:
            return Result.failure(ValidationError("ics_file_too_large", "ics_file_too_large"))
        try:
            calendar = Calendar.from_ical(raw)
            if calendar.name != "VCALENDAR":
                raise ValueError("ics_import_failed")
            for component in calendar.walk("VEVENT"):
                for field, maximum in (("SUMMARY", 1024), ("DESCRIPTION", 65536), ("LOCATION", 4096)):
                    if len(str(component.get(field, "")).encode("utf-8")) > maximum:
                        raise ValueError("ics_file_too_large")
                rule = component.get("RRULE")
                if rule and "COUNT" not in rule and "UNTIL" not in rule:
                    raise ValueError("ics_recurrence_unbounded")
                if rule and "COUNT" in rule:
                    counts = rule["COUNT"]
                    if len(counts) != 1 or not 1 <= int(counts[0]) <= self._max_events:
                        raise ValueError("ics_file_too_large")
                if component.errors or "DTSTART" not in component:
                    raise ValueError("ics_import_failed")
                for field in ("DTSTART", "DTEND"):
                    value = component.get(field)
                    if value is not None and value.params.get("TZID") and isinstance(value.dt, datetime) and value.dt.tzinfo is None:
                        raise ValueError("ics_import_failed")
            zone = self._timezone or get_localzone()
            calendar = prepare_recurrence_calendar(calendar, self._max_events)
            events = []
            for index, component in enumerate(recurring_ical_events.of(calendar).all()):
                if index >= self._max_events:
                    raise ValueError("ics_file_too_large")
                if str(component.get("STATUS", "")).upper() == "CANCELLED":
                    continue
                for event in _daily_events(component, user_id, Path(source).name, zone):
                    events.append(event)
                    if len(events) > self._max_events:
                        raise ValueError("ics_file_too_large")
            return Result.success(tuple(events))
        except ValueError as exc:
            code = str(exc) if str(exc) in {"ics_recurrence_unbounded", "ics_recurrence_unsupported", "ics_file_too_large"} else "ics_import_failed"
            return Result.failure(ValidationError(code, code))
        except Exception:
            return Result.failure(ValidationError("ics_import_failed", "ics_import_failed"))


def _daily_events(component, user_id: int, source: str, zone: tzinfo):
    summary = str(component.get("SUMMARY", "")).strip()
    description = str(component.get("DESCRIPTION", ""))
    location = str(component.get("LOCATION", ""))
    if not summary:
        return
    start = component.decoded("DTSTART")
    end = component.decoded("DTEND", start)
    all_day = not isinstance(start, datetime)
    if all_day:
        start_day, stop_day = start, end
        if stop_day <= start_day:
            stop_day = start_day + timedelta(days=1)
    else:
        start = start.astimezone(zone) if start.tzinfo else start.replace(tzinfo=zone)
        end = end.astimezone(zone) if end.tzinfo else end.replace(tzinfo=zone)
        if end < start:
            raise ValueError("ics_import_failed")
        start_day = start.date()
        stop_day = end.date() + (timedelta(days=1) if end.time() != time.min or end == start else timedelta())
    day = start_day
    while day < stop_day:
        yield CalendarEvent(
            id=None, user_id=user_id, day=day, summary=summary,
            start_time=None if all_day else (start.strftime("%H:%M") if day == start.date() else "00:00"),
            end_time=None if all_day else (end.strftime("%H:%M") if day == end.date() else "24:00"),
            description=description,
            location=location, all_day=all_day, source_file=source,
        )
        day += timedelta(days=1)
