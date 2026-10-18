"""Prepare finite recurrence rules with bounded expansion work and payload."""

from copy import deepcopy
from datetime import datetime, time, timedelta, timezone
from itertools import islice

from dateutil.rrule import rrulestr


_PERIOD_DAYS = {"DAILY": 1, "WEEKLY": 7, "MONTHLY": 31, "YEARLY": 366}
_MAXIMUM_PERIODS = 100_000
_MAXIMUM_PAYLOAD = 16 * 1024 * 1024


def prepare_recurrence_calendar(calendar, maximum: int):
    prepared = deepcopy(calendar)
    used, payload = 0, 0
    for component in prepared.walk("VEVENT"):
        if "RECURRENCE-ID" in component:
            continue
        original_start = component.decoded("DTSTART")
        start = original_start if isinstance(original_start, datetime) else datetime.combine(original_start, time.min)
        before = used
        rules = tuple(rule for field in ("RRULE", "EXRULE") for rule in _values(component, field))
        used += not rules
        for rule in rules:
            occurrences = _bounded_occurrences(rule, start, maximum - used)
            used += len(occurrences)
            if "COUNT" in rule:
                del rule["COUNT"]
                last = occurrences[-1]
                rule["UNTIL"] = [(last.astimezone(timezone.utc) if last.tzinfo else last)
                                 if isinstance(original_start, datetime) else last.date()]
        used += sum(len(dates.dts) for field in ("RDATE", "EXDATE") for dates in _values(component, field))
        if used > maximum:
            raise ValueError("ics_file_too_large")
        end = component.decoded("DTEND", original_start)
        stop_day = end.date() if isinstance(end, datetime) else end
        span = max(1, stop_day.toordinal() - start.date().toordinal() + 1)
        payload += max(1, used - before) * span * len(component.to_ical())
        if payload > _MAXIMUM_PAYLOAD:
            raise ValueError("ics_file_too_large")
    return prepared


def _values(component, field):
    value = component.get(field)
    return value if isinstance(value, list) else (value,) if value else ()


def _bounded_occurrences(rule, start, remaining):
    if "COUNT" not in rule and "UNTIL" not in rule:
        raise ValueError("ics_recurrence_unbounded")
    frequency = str(rule.get("FREQ", [""])[0]).upper()
    if frequency not in _PERIOD_DAYS:
        raise ValueError("ics_file_too_large")
    interval = int(rule.get("INTERVAL", [1])[0])
    if interval < 1:
        raise ValueError("ics_import_failed")
    count = None
    if "COUNT" in rule:
        counts = rule["COUNT"]
        if len(counts) != 1 or int(counts[0]) < 1:
            raise ValueError("ics_import_failed")
        count = int(counts[0])
        if count > remaining:
            raise ValueError("ics_file_too_large")
    try:
        boundary = start + timedelta(days=_MAXIMUM_PERIODS * interval * _PERIOD_DAYS[frequency])
    except OverflowError:
        boundary = datetime.max.replace(tzinfo=start.tzinfo)
    until = rule.get("UNTIL", [None])[0]
    if until is not None and not isinstance(until, datetime):
        until = datetime.combine(until, time.min).replace(tzinfo=start.tzinfo)
    if until is not None and (until.tzinfo is None) != (start.tzinfo is None):
        raise ValueError("ics_import_failed")
    if until is not None and until > boundary:
        raise ValueError("ics_file_too_large")
    recurrence = rrulestr(rule.to_ical().decode("ascii"), dtstart=start)
    occurrences = tuple(islice(recurrence.replace(count=None, until=until or boundary),
                              count if count is not None else max(0, remaining) + 1))
    if len(occurrences) > remaining or count is not None and len(occurrences) != count:
        raise ValueError("ics_file_too_large")
    return occurrences
