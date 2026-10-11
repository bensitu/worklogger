"""Incremental conflict checks preserving source order without timezone guesses."""

from bisect import bisect_left

from worklogger.domain.worklog.rules import entry_interval, wall_interval


class _IntervalIndex:
    def __init__(self, starts):
        self._starts = sorted(set(starts))
        self._ends = [None] * (len(self._starts) + 1)

    def conflicts(self, start, end):
        index = bisect_left(self._starts, end)
        latest = None
        while index:
            value = self._ends[index]
            if value is not None and (latest is None or value > latest):
                latest = value
            index -= index & -index
        return latest is not None and latest > start

    def add(self, start, end):
        index = bisect_left(self._starts, start) + 1
        while index < len(self._ends):
            if self._ends[index] is None or end > self._ends[index]:
                self._ends[index] = end
            index += index & -index


class EntryIntervalIndex:
    def __init__(self, records):
        self._intervals = {}
        wall_starts, utc_starts = [], []
        for record in records:
            wall = wall_interval(record)
            if wall is None:
                continue
            captured = record.started_at is not None and record.ended_at is not None
            utc = entry_interval(record) if captured else None
            self._intervals[id(record)] = (record, wall, utc)
            wall_starts.append((record.user_id, wall[0]))
            if utc:
                utc_starts.append((record.user_id, utc[0]))
        self._captured = _IntervalIndex(utc_starts)
        self._legacy = _IntervalIndex(wall_starts)
        self._wall = _IntervalIndex(wall_starts)

    def add(self, record) -> bool:
        intervals = self._intervals.get(id(record))
        if intervals is None:
            if record.has_times:
                raise ValueError("time_range_invalid")
            return True
        _record, wall, utc = intervals
        start, end = (record.user_id, wall[0]), (record.user_id, wall[1])
        if utc:
            utc_start, utc_end = (record.user_id, utc[0]), (record.user_id, utc[1])
            if self._captured.conflicts(utc_start, utc_end) or self._legacy.conflicts(start, end):
                return False
            self._captured.add(utc_start, utc_end)
        else:
            if self._wall.conflicts(start, end):
                return False
            self._legacy.add(start, end)
        self._wall.add(start, end)
        return True
