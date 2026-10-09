"""Work log time, validation, and classification rules."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone, tzinfo
import math

from worklogger.config.constants import MAX_SHIFT_HOURS, WORK_TYPE_KEYS
from worklogger.domain.worklog.models import WorkLog, WorkType, CustomWorkType


def parse_time(raw: str | None) -> str | None:
    if raw is None or not str(raw).strip():
        return None
    text = str(raw).strip().replace("：", ":")
    if "." in text:
        hour_text, _separator, minute_text = text.partition(".")
        if not hour_text.isdecimal() or len(minute_text) != 2 or not minute_text.isdecimal():
            return None
        text = hour_text + ":" + minute_text

    try:
        return datetime.strptime(text, "%H:%M").strftime("%H:%M")
    except ValueError:
        pass

    digits = text.replace(":", "").replace(" ", "")
    if digits.isdecimal():
        length = len(digits)
        if length <= 2:
            hour, minute = int(digits), 0
        elif length == 3:
            hour, minute = int(digits[0]), int(digits[1:])
        else:
            hour, minute = int(digits[:-2]), int(digits[-2:])
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"

    if ":" in text:
        hour_text, minute_text = text.split(":", 1)
        try:
            hour = int(hour_text)
            minute = int(minute_text) if minute_text else 0
        except ValueError:
            return None
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"

    return None


def parse_minutes(hhmm: str | None) -> int | None:
    normalized = parse_time(hhmm)
    if normalized is None:
        return None
    hour_text, minute_text = normalized.split(":", 1)
    return int(hour_text) * 60 + int(minute_text)


def calc_shift_span_hours(
    start: str,
    end: str,
    *,
    max_shift_hours: float = MAX_SHIFT_HOURS,
) -> float | None:
    start_minutes = parse_minutes(start)
    end_minutes = parse_minutes(end)
    if start_minutes is None or end_minutes is None:
        return None

    delta_minutes = end_minutes - start_minutes
    if delta_minutes <= 0:
        delta_minutes += 24 * 60

    span = delta_minutes / 60.0
    if span <= 0 or span > float(max_shift_hours):
        return None
    return span


def is_overnight_shift(start: str, end: str) -> bool:
    start_minutes = parse_minutes(start)
    end_minutes = parse_minutes(end)
    if start_minutes is None or end_minutes is None:
        return False
    return end_minutes <= start_minutes


def timestamp_span_hours(start: datetime, end: datetime) -> float:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("time_range_invalid")
    return (end.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds() / 3600


def shift_datetimes(day: date, start: str, end: str, local_timezone: tzinfo | None = None) -> tuple[datetime, datetime] | None:
    start_time = parse_time(start)
    end_time = parse_time(end)
    if start_time is None or end_time is None:
        return None
    try:
        start_dt = datetime.strptime(f"{day.isoformat()} {start_time}", "%Y-%m-%d %H:%M")
        end_dt = datetime.strptime(f"{day.isoformat()} {end_time}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)
    if local_timezone is not None:
        start_dt = start_dt.replace(tzinfo=local_timezone)
        end_dt = end_dt.replace(tzinfo=local_timezone)
        for moment in (start_dt, end_dt):
            if moment.astimezone(timezone.utc).astimezone(local_timezone).replace(tzinfo=None) != moment.replace(tzinfo=None):
                raise ValueError("time_range_invalid")
    return start_dt, end_dt


def calc_hours(
    start: str,
    end: str,
    break_hours: float | None,
    *,
    max_shift_hours: float = MAX_SHIFT_HOURS,
) -> float:
    span = calc_shift_span_hours(start, end, max_shift_hours=max_shift_hours)
    if span is None:
        return 0.0
    try:
        break_value = float(break_hours or 0)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(break_value) or break_value < 0 or break_value >= span:
        return 0.0
    return max(span - break_value, 0.0)


def normalize_work_type(raw: str | WorkType | CustomWorkType | None) -> WorkType | CustomWorkType:
    if isinstance(raw, (WorkType, CustomWorkType)):
        return raw
    value = str(raw or WorkType.NORMAL.value)
    if value not in WORK_TYPE_KEYS:
        return WorkType.NORMAL
    return WorkType(value)


def decode_work_type(value: str, label: str = "", category: str = "", *, strict: bool = False):
    if isinstance(value, str) and value.startswith("custom:"):
        return CustomWorkType(value, label, category)
    return WorkType(value) if strict else normalize_work_type(value)


def normalize_work_log(
    work_log: WorkLog,
    *,
    max_shift_hours: float = MAX_SHIFT_HOURS,
) -> WorkLog:
    if work_log.entries:
        raise ValueError("worklog_summary_not_editable")
    start = parse_time(work_log.start_time)
    end = parse_time(work_log.end_time)
    if (work_log.start_time and not start) or (work_log.end_time and not end):
        raise ValueError("time_range_invalid")
    if bool(start) != bool(end):
        raise ValueError("time_range_incomplete")
    if not start and ((isinstance(work_log.work_type, CustomWorkType) and work_log.work_type.category != "leave") or normalize_work_type(work_log.work_type) in {WorkType.MEETING, WorkType.TRAINING, WorkType.BREAK, WorkType.OTHER}):
        raise ValueError("time_range_incomplete")

    break_hours = float(work_log.break_hours or 0)
    if not math.isfinite(break_hours) or break_hours > max_shift_hours:
        raise ValueError("break_hours_too_long")
    if break_hours < 0:
        raise ValueError("break_hours_negative")

    if start and end:
        if work_log.started_at is not None or work_log.ended_at is not None:
            if work_log.started_at is None or work_log.ended_at is None:
                raise ValueError("time_range_incomplete")
            if (work_log.started_at.date() != work_log.day or work_log.started_at.strftime("%H:%M") != start
                    or work_log.ended_at.strftime("%H:%M") != end):
                raise ValueError("time_range_invalid")
            span = timestamp_span_hours(work_log.started_at, work_log.ended_at)
            if span <= 0 or span > max_shift_hours:
                raise ValueError("time_range_invalid")
        else:
            span = calc_shift_span_hours(start, end, max_shift_hours=max_shift_hours)
        if span is None:
            raise ValueError("time_range_invalid")
        if break_hours >= span:
            raise ValueError("break_hours_too_long")
    elif work_log.started_at is not None or work_log.ended_at is not None:
        raise ValueError("time_range_incomplete")

    return replace(
        work_log,
        start_time=start,
        end_time=end,
        break_hours=break_hours,
        work_type=normalize_work_type(work_log.work_type),
        overnight=(work_log.ended_at.date() > work_log.started_at.date()) if work_log.started_at and work_log.ended_at
        else is_overnight_shift(start, end) if start and end else False,
    )


def aggregate_days(records) -> tuple[WorkLog, ...]:
    grouped = {}
    for record in records:
        grouped.setdefault((record.user_id, record.day), []).append(record)
    result = []
    for (user_id, day), entries in sorted(grouped.items()):
        if len(entries) == 1:
            result.append(entries[0])
            continue
        entries.sort(key=lambda entry: (entry.start_time or "", entry.id or 0))
        result.append(WorkLog(user_id, day, entries[0].start_time, entries[-1].end_time,
                              sum(entry.break_hours for entry in entries),
                              "\n".join(entry.note for entry in entries if entry.note),
                              entries[0].work_type if all(entry.is_leave for entry in entries) else WorkType.NORMAL,
                              entries=tuple(entries)))
    return tuple(result)


def entry_interval(record: WorkLog) -> tuple[datetime, datetime] | None:
    if not record.has_times:
        return None
    if record.started_at is not None and record.ended_at is not None:
        return record.started_at.astimezone(timezone.utc), record.ended_at.astimezone(timezone.utc)
    times = shift_datetimes(record.day, record.start_time, record.end_time)
    return tuple(moment.astimezone(timezone.utc) for moment in times)


def entries_overlap(left: WorkLog, right: WorkLog) -> bool:
    if left.is_note_only or right.is_note_only:
        return False
    a, b = entry_interval(left), entry_interval(right)
    if a is None or b is None:
        return left.day == right.day and (left.is_leave or right.is_leave)
    return a[0] < b[1] and b[0] < a[1]
