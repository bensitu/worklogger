"""Interval transformations that conserve recorded time and historical accounting."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from worklogger.domain.worklog.models import WorkLog, EntryType, TimeRange
from worklogger.domain.projects.models import WorkContext
from worklogger.domain.worklog.rules import entry_interval, normalize_work_log, slice_entry
from worklogger.domain.worklog.content import require_entry_content


@dataclass(frozen=True)
class EntryChangeInfo:
    id: int
    operation: str
    entry: WorkLog
    entries: tuple[WorkLog, ...] = ()


def split_entry(record: WorkLog, first_minutes: int) -> tuple[WorkLog, WorkLog]:
    if type(first_minutes) is not int or first_minutes < 1 or not record.has_times:
        raise ValueError("record_split_invalid")
    start, _end = entry_interval(record) if record.started_at else TimeRange(record.start_time, record.end_time).as_datetimes(record.day)
    return split_entry_at(record, start + timedelta(minutes=first_minutes))


def split_entry_at(record: WorkLog, cut: datetime) -> tuple[WorkLog, WorkLog]:
    if record.break_hours:
        raise ValueError("historical_break_placement_required")
    if record.entries or not record.has_times or not isinstance(cut, datetime):
        raise ValueError("record_split_invalid")
    start, end = entry_interval(record) if record.started_at else TimeRange(record.start_time, record.end_time).as_datetimes(record.day)
    if (cut.tzinfo is None) != (start.tzinfo is None):
        raise ValueError("record_split_invalid")
    if record.started_at is None and (cut.second or cut.microsecond):
        raise ValueError("record_split_invalid")
    if not start < cut < end:
        raise ValueError("record_split_invalid")
    return slice_entry(record, start, cut, keep_identity=True), slice_entry(record, cut, end, keep_identity=False)


def merge_entries(left: WorkLog, right: WorkLog) -> WorkLog:
    first = entry_interval(left) if left.started_at else TimeRange(left.start_time, left.end_time).as_datetimes(left.day) if left.has_times else None
    second = entry_interval(right) if right.started_at else TimeRange(right.start_time, right.end_time).as_datetimes(right.day) if right.has_times else None
    if (left.user_id != right.user_id or left.entries or right.entries or first is None or second is None or first[1] != second[0]
            or left.entry_type != right.entry_type or left.work_mode != right.work_mode or left.context != right.context
            or bool(left.started_at) != bool(right.started_at)):
        raise ValueError("record_merge_invalid")
    content = left.note if left.note == right.note else "\n\n".join(value for value in (left.note, right.note) if value)
    content = require_entry_content(content)
    return normalize_work_log(replace(left, end_time=right.end_time, ended_at=right.ended_at,
                                     note=content, break_hours=left.break_hours + right.break_hours))


def place_historical_break(record: WorkLog, first_minutes: int) -> tuple[WorkLog, ...]:
    if not record.break_hours or record.is_break or not record.has_times or type(first_minutes) is not int or first_minutes < 0:
        raise ValueError("historical_break_placement_invalid")
    break_minutes = round(record.break_hours * 60)
    if abs(break_minutes - record.break_hours * 60) > 1e-8:
        raise ValueError("historical_break_precision_invalid")
    start, end = entry_interval(record) if record.started_at else TimeRange(record.start_time, record.end_time).as_datetimes(record.day)
    before_break = start + timedelta(minutes=first_minutes)
    after_break = before_break + timedelta(minutes=break_minutes)
    if break_minutes <= 0 or not start <= before_break < after_break <= end:
        raise ValueError("historical_break_placement_invalid")
    boundaries = ((start, before_break, False), (before_break, after_break, True), (after_break, end, False))
    result = []
    for left, right, is_break in boundaries:
        if left == right:
            continue
        if record.started_at:
            left, right = left.astimezone(record.started_at.tzinfo), right.astimezone(record.ended_at.tzinfo if right == end else record.started_at.tzinfo)
        entry = replace(record, id=record.id if not result else None, revision=record.revision if not result else 0,
            capture_id=record.capture_id if not result else None, day=left.date(), start_time=left.strftime("%H:%M"), end_time=right.strftime("%H:%M"),
            started_at=left if record.started_at else None, ended_at=right if record.started_at else None,
            break_hours=0, entry_type=EntryType.BREAK if is_break else record.entry_type,
            note="" if is_break else record.note, context=WorkContext() if is_break else record.context,
            work_mode=None if is_break else record.work_mode)
        result.append(normalize_work_log(entry))
    return tuple(result)
