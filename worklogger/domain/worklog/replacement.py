"""Explicit replacement plans that preserve unaffected recorded periods."""

from dataclasses import dataclass

from worklogger.domain.worklog.models import WorkLog
from worklogger.domain.worklog.rules import entries_overlap, entry_interval, normalize_work_log, shift_datetimes, slice_entry


def _remaining(record: WorkLog, incoming: WorkLog) -> tuple[WorkLog, ...]:
    if not record.has_times:
        raise ValueError("record_replacement_requires_times")
    captured = record.started_at is not None and incoming.started_at is not None
    if captured:
        start, end = entry_interval(record)
        cut_start, cut_end = entry_interval(incoming)
    else:
        if any(item.started_at and item.started_at.utcoffset() != item.ended_at.utcoffset()
               for item in (record, incoming)):
            raise ValueError("record_replacement_timezone_ambiguous")
        start, end = shift_datetimes(record.day, record.start_time, record.end_time)
        cut_start, cut_end = shift_datetimes(incoming.day, incoming.start_time, incoming.end_time)
    bounds = [(left, right) for left, right in ((start, min(end, cut_start)), (max(start, cut_end), end)) if left < right]
    if bounds and record.break_hours:
        raise ValueError("historical_break_placement_required")
    result = []
    for left, right in bounds:
        if not captured and record.started_at is not None:
            left, right = left.replace(tzinfo=record.started_at.tzinfo), right.replace(tzinfo=record.ended_at.tzinfo)
        result.append(slice_entry(record, left, right, keep_identity=not result))
    return tuple(result)


@dataclass(frozen=True)
class EntryReplacement:
    incoming: WorkLog
    conflicts: tuple[WorkLog, ...]
    original: WorkLog | None = None

    @property
    def affected(self) -> tuple[WorkLog, ...]:
        return ((self.original,) if self.original is not None else ()) + self.conflicts

    def periods(self, *, keep_outside: bool) -> tuple[WorkLog, ...]:
        record = normalize_work_log(self.incoming)
        if len(self.affected) > 250:
            raise ValueError("record_change_too_large")
        if (not record.has_times or not self.conflicts
                or len({item.id for item in self.affected}) != len(self.affected)
                or any(item.user_id != record.user_id or item.id is None or item.id <= 0 for item in self.affected)
                or (record.id is not None and (self.original is None or self.original.id != record.id))
                or (self.original is not None and (self.original.id != record.id or self.original.revision != record.revision))
                or any(item.id == record.id or not entries_overlap(item, record) for item in self.conflicts)):
            raise ValueError("record_batch_invalid")
        result = [record]
        if keep_outside:
            for conflict in self.conflicts:
                result.extend(_remaining(conflict, record))
        if len(result) > 250:
            raise ValueError("record_change_too_large")
        return tuple(result)
