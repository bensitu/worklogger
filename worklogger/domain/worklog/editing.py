"""Interval transformations that conserve recorded time and historical accounting."""

from dataclasses import dataclass, replace
from datetime import timedelta
from worklogger.domain.worklog.models import WorkLog, WorkType, TimeRange
from worklogger.domain.projects.models import WorkContext
from worklogger.domain.worklog.rules import entry_interval, normalize_work_log


@dataclass(frozen=True)
class EntryChangeInfo:
    id: int
    operation: str
    entry: WorkLog


def split_entry(record: WorkLog, first_minutes: int) -> tuple[WorkLog, WorkLog]:
    if record.break_hours:
        raise ValueError("historical_break_placement_required")
    if record.entries or not record.has_times or type(first_minutes) is not int or first_minutes < 1:
        raise ValueError("record_split_invalid")
    start, end = entry_interval(record) if record.started_at else TimeRange(record.start_time, record.end_time).as_datetimes(record.day)
    cut = start + timedelta(minutes=first_minutes)
    if not start < cut < end:
        raise ValueError("record_split_invalid")
    if record.started_at:
        cut = cut.astimezone(record.started_at.tzinfo)
    left = replace(record, end_time=cut.strftime("%H:%M"), ended_at=cut if record.started_at else None)
    right = replace(record, id=None, revision=0, capture_id=None, day=cut.date(),
                    start_time=cut.strftime("%H:%M"), started_at=cut if record.started_at else None)
    return normalize_work_log(left), normalize_work_log(right)


def merge_entries(left: WorkLog, right: WorkLog) -> WorkLog:
    first, second = entry_interval(left), entry_interval(right)
    if (left.entries or right.entries or first is None or second is None or first[1] != second[0]
            or left.work_type != right.work_type or left.context != right.context
            or bool(left.started_at) != bool(right.started_at)):
        raise ValueError("record_merge_invalid")
    content = left.note if left.note == right.note else "\n\n".join(value for value in (left.note, right.note) if value)
    if len(content) > 16000:
        raise ValueError("time_entry_content_too_long")
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
            break_hours=0, work_type=WorkType.BREAK if is_break else record.work_type,
            note="" if is_break else record.note, context=WorkContext() if is_break else record.context)
        result.append(normalize_work_log(entry))
    return tuple(result)
