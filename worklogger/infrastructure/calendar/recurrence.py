"""Bound recurrence capacity before materializing calendar query windows."""

from datetime import datetime, time
from itertools import islice

from dateutil.rrule import rrulestr


def validate_recurrence_capacity(calendar, maximum: int) -> None:
    used = 0
    for component in calendar.walk("VEVENT"):
        if "RECURRENCE-ID" in component:
            continue
        start = component.decoded("DTSTART")
        if not isinstance(start, datetime):
            start = datetime.combine(start, time.min)
        rules = []
        for field in ("RRULE", "EXRULE"):
            value = component.get(field)
            rules.extend(value if isinstance(value, list) else (value,) if value else ())
        if not rules:
            used += 1
        for rule in rules:
            if "COUNT" not in rule and "UNTIL" not in rule:
                raise ValueError("ics_recurrence_unbounded")
            if "COUNT" in rule:
                counts = rule["COUNT"]
                if len(counts) != 1 or int(counts[0]) < 1:
                    raise ValueError("ics_import_failed")
                used += int(counts[0])
            else:
                recurrence = rrulestr(rule.to_ical().decode("ascii"), dtstart=start)
                used += sum(1 for _occurrence in islice(recurrence, max(0, maximum - used) + 1))
            if used > maximum:
                raise ValueError("ics_file_too_large")
        for field in ("RDATE", "EXDATE"):
            value = component.get(field)
            for dates in value if isinstance(value, list) else (value,) if value else ():
                used += len(dates.dts)
        if used > maximum:
            raise ValueError("ics_file_too_large")
