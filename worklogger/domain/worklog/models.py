"""Work log domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from uuid import UUID
from worklogger.config.constants import DEFAULT_LEAVE_HOURS, LEAVE_TYPES, MAX_SHIFT_HOURS


@dataclass(frozen=True)
class CustomWorkType:
    value: str
    label: str
    category: str = "work"
    revision: int = 0
    archived: bool = False

    def __post_init__(self):
        if not isinstance(self.value, str) or len(self.value) != 39 or not self.value.startswith("custom:"):
            raise ValueError("work_type_invalid")
        try:
            valid_id = UUID(self.value[7:]).hex == self.value[7:]
        except ValueError:
            valid_id = False
        if not valid_id or not isinstance(self.label, str) or not self.label.strip() or len(self.label) > 80 or any(ord(char) < 32 for char in self.label):
            raise ValueError("work_type_invalid")
        if self.category not in {"work", "break", "leave"} or not isinstance(self.revision, int) or self.revision < 0:
            raise ValueError("work_type_invalid")

class WorkType(str, Enum):
    NORMAL = "normal"
    REMOTE = "remote"
    BUSINESS_TRIP = "business_trip"
    PAID_LEAVE = "paid_leave"
    COMP_LEAVE = "comp_leave"
    SICK_LEAVE = "sick_leave"
    MEETING = "meeting"
    TRAINING = "training"
    BREAK = "break"
    OTHER = "other"


@dataclass(frozen=True)
class TimeRange:
    start: str
    end: str

    @property
    def overnight(self) -> bool:
        from worklogger.domain.worklog.rules import is_overnight_shift

        return is_overnight_shift(self.start, self.end)

    def span_hours(self, *, max_shift_hours: float = MAX_SHIFT_HOURS) -> float | None:
        from worklogger.domain.worklog.rules import calc_shift_span_hours

        return calc_shift_span_hours(
            self.start,
            self.end,
            max_shift_hours=max_shift_hours,
        )

    def as_datetimes(self, day: date) -> tuple[datetime, datetime] | None:
        from worklogger.domain.worklog.rules import shift_datetimes

        return shift_datetimes(day, self.start, self.end)


@dataclass(frozen=True)
class WorkLog:
    user_id: int
    day: date
    start_time: str | None = None
    end_time: str | None = None
    break_hours: float = 0.0
    note: str = ""
    work_type: WorkType | CustomWorkType = WorkType.NORMAL
    overnight: bool = False
    started_at: datetime | None = None
    ended_at: datetime | None = None
    id: int | None = None
    revision: int = 0
    capture_id: str | None = None
    entries: tuple[WorkLog, ...] = ()

    @property
    def has_times(self) -> bool:
        return bool(self.start_time and self.end_time)

    @property
    def is_note_only(self) -> bool:
        return not self.has_times and self.work_type == WorkType.NORMAL and self.break_hours == 0 and bool(self.note)

    @property
    def is_leave(self) -> bool:
        if self.entries:
            return all(entry.is_leave for entry in self.entries)
        if isinstance(self.work_type, CustomWorkType):
            return self.work_type.category == "leave"
        from worklogger.domain.worklog.rules import normalize_work_type

        return normalize_work_type(self.work_type).value in LEAVE_TYPES

    @property
    def is_break(self) -> bool:
        if self.entries:
            return all(entry.is_break for entry in self.entries)
        return self.work_type.category == "break" if isinstance(self.work_type, CustomWorkType) else self.work_type == WorkType.BREAK

    @property
    def is_overnight(self) -> bool:
        if self.entries:
            return any(entry.is_overnight for entry in self.entries)
        if self.started_at is not None and self.ended_at is not None:
            return self.ended_at.date() > self.started_at.date()
        if self.has_times:
            from worklogger.domain.worklog.rules import is_overnight_shift

            return self.overnight or is_overnight_shift(
                str(self.start_time),
                str(self.end_time),
            )
        return bool(self.overnight)

    def worked_hours(self, *, max_shift_hours: float = MAX_SHIFT_HOURS) -> float:
        if self.entries:
            return sum(entry.worked_hours(max_shift_hours=max_shift_hours) for entry in self.entries)
        if not self.has_times or self.is_leave or self.is_break:
            return 0.0
        if self.started_at is not None and self.ended_at is not None:
            return self.raw_hours(max_shift_hours=max_shift_hours)
        from worklogger.domain.worklog.rules import calc_hours

        return calc_hours(
            str(self.start_time),
            str(self.end_time),
            self.break_hours,
            max_shift_hours=max_shift_hours,
        )

    def raw_hours(self, *, max_shift_hours: float = MAX_SHIFT_HOURS) -> float:
        if self.entries:
            return sum(entry.raw_hours(max_shift_hours=max_shift_hours) for entry in self.entries)
        if not self.has_times:
            return 0.0
        if self.started_at is not None and self.ended_at is not None:
            from worklogger.domain.worklog.rules import timestamp_span_hours

            span = timestamp_span_hours(self.started_at, self.ended_at)
            return max(span - self.break_hours, 0.0) if 0 < span <= max_shift_hours else 0.0
        from worklogger.domain.worklog.rules import calc_hours

        return calc_hours(
            str(self.start_time),
            str(self.end_time),
            self.break_hours,
            max_shift_hours=max_shift_hours,
        )

    def leave_hours(self, *, standard_hours: float = DEFAULT_LEAVE_HOURS) -> float:
        if self.entries:
            return sum(entry.leave_hours(standard_hours=standard_hours) for entry in self.entries)
        if not self.is_leave:
            return 0.0
        raw = self.raw_hours()
        return raw if raw > 0 else max(float(standard_hours or DEFAULT_LEAVE_HOURS), 0.0)
