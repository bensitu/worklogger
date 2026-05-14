"""Work log domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

from worklogger.config.constants import DEFAULT_LEAVE_HOURS, LEAVE_TYPES, MAX_SHIFT_HOURS


class WorkType(str, Enum):
    NORMAL = "normal"
    REMOTE = "remote"
    BUSINESS_TRIP = "business_trip"
    PAID_LEAVE = "paid_leave"
    COMP_LEAVE = "comp_leave"
    SICK_LEAVE = "sick_leave"


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
    work_type: WorkType = WorkType.NORMAL
    overnight: bool = False

    @property
    def has_times(self) -> bool:
        return bool(self.start_time and self.end_time)

    @property
    def is_leave(self) -> bool:
        from worklogger.domain.worklog.rules import normalize_work_type

        return normalize_work_type(self.work_type).value in LEAVE_TYPES

    @property
    def is_overnight(self) -> bool:
        if self.has_times:
            from worklogger.domain.worklog.rules import is_overnight_shift

            return self.overnight or is_overnight_shift(
                str(self.start_time),
                str(self.end_time),
            )
        return bool(self.overnight)

    def worked_hours(self, *, max_shift_hours: float = MAX_SHIFT_HOURS) -> float:
        if not self.has_times or self.is_leave:
            return 0.0
        from worklogger.domain.worklog.rules import calc_hours

        return calc_hours(
            str(self.start_time),
            str(self.end_time),
            self.break_hours,
            max_shift_hours=max_shift_hours,
        )

    def raw_hours(self, *, max_shift_hours: float = MAX_SHIFT_HOURS) -> float:
        if not self.has_times:
            return 0.0
        from worklogger.domain.worklog.rules import calc_hours

        return calc_hours(
            str(self.start_time),
            str(self.end_time),
            self.break_hours,
            max_shift_hours=max_shift_hours,
        )

    def leave_hours(self, *, standard_hours: float = DEFAULT_LEAVE_HOURS) -> float:
        if not self.is_leave:
            return 0.0
        raw = self.raw_hours()
        return raw if raw > 0 else max(float(standard_hours or DEFAULT_LEAVE_HOURS), 0.0)
