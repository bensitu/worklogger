"""Bound recurrence capacity before materializing calendar query windows."""

from datetime import datetime, time, timedelta, timezone
from itertools import islice

from dateutil.rrule import rrulestr


def validate_recurrence_capacity(calendar, maximum: int) -> None:
    used = 0
    payload = 0
    for component in calendar.walk("VEVENT"):
        if "RECURRENCE-ID" in component:
            continue
        start = component.decoded("DTSTART")
        if not isinstance(start, datetime):
            start = datetime.combine(start, time.min)
        try:
            boundary = start + timedelta(days=3660)
        except OverflowError:
            boundary = datetime.max.replace(tzinfo=start.tzinfo)
        before = used
        rules = []
        for field in ("RRULE", "EXRULE"):
            value = component.get(field)
            rules.extend(value if isinstance(value, list) else (value,) if value else ())
        if not rules:
            used += 1
        for rule in rules:
            if "COUNT" not in rule and "UNTIL" not in rule:
                raise ValueError("ics_recurrence_unbounded")
            if str(rule.get("FREQ", [""])[0]).upper() in {"SECONDLY", "MINUTELY", "HOURLY"}:
                raise ValueError("ics_file_too_large")
            count = None
            if "COUNT" in rule:
                counts = rule["COUNT"]
                if len(counts) != 1 or int(counts[0]) < 1:
                    raise ValueError("ics_import_failed")
                count = int(counts[0])
                if count > maximum - used:
                    raise ValueError("ics_file_too_large")
            recurrence = rrulestr(rule.to_ical().decode("ascii"), dtstart=start)
            until = rule.get("UNTIL", [None])[0]
            if until is not None and not isinstance(until, datetime):
                until = datetime.combine(until, time.min).replace(tzinfo=start.tzinfo)
            if until is not None and until > boundary:
                raise ValueError("ics_file_too_large")
            occurrences = tuple(islice(recurrence.replace(count=None, until=until or boundary),
                                      count if count is not None else max(0, maximum - used) + 1))
            if not occurrences or count is not None and len(occurrences) != count:
                raise ValueError("ics_import_failed")
            used += len(occurrences)
            if count is not None:
                del rule["COUNT"]
                last = occurrences[-1]
                rule["UNTIL"] = [last.astimezone(timezone.utc) if last.tzinfo else last]
            if used > maximum:
                raise ValueError("ics_file_too_large")
        for field in ("RDATE", "EXDATE"):
            value = component.get(field)
            for dates in value if isinstance(value, list) else (value,) if value else ():
                used += len(dates.dts)
        if used > maximum:
            raise ValueError("ics_file_too_large")
        end = component.decoded("DTEND", component.decoded("DTSTART"))
        span = max(1, (end.date() if isinstance(end, datetime) else end).toordinal() - start.date().toordinal() + 1)
        size = len(component.to_ical())
        payload += max(1, used - before) * span * size
        if payload > 16 * 1024 * 1024:
            raise ValueError("ics_file_too_large")
