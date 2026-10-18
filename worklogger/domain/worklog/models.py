"""Work log domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum, StrEnum
from uuid import UUID
from worklogger.domain.projects.models import WorkContext
from worklogger.config.constants import DEFAULT_LEAVE_HOURS, LEAVE_TYPES, MAX_SHIFT_HOURS


class EntryCategory(StrEnum):
    WORK = "work"
    BREAK = "break"
    LEAVE = "leave"


class WorkMode(StrEnum):
    ONSITE = "onsite"
    REMOTE = "remote"
    BUSINESS_TRIP = "business_trip"
    OTHER = "other"


def _validate_custom_definition(value, label, error_code):
    try:
        valid_id = isinstance(value, str) and len(value) == 39 and value.startswith("custom:") and UUID(value[7:]).hex == value[7:]
    except ValueError:
        valid_id = False
    if (not valid_id or not isinstance(label, str) or not label.strip()
            or len(label) > 80 or any(ord(char) < 32 for char in label)):
        raise ValueError(error_code)


@dataclass(frozen=True)
class CustomWorkMode:
    value: str
    label: str
    revision: int = 0
    archived: bool = False

    def __post_init__(self):
        _validate_custom_definition(self.value, self.label, "work_mode_invalid")
        if type(self.revision) is not int or self.revision < 0:
            raise ValueError("work_mode_invalid")

    @property
    def category(self):
        return EntryCategory.WORK


WorkModeValue = WorkMode | CustomWorkMode


def decode_work_mode(value, label="") -> WorkModeValue | None:
    if isinstance(value, CustomWorkMode):
        return value
    if isinstance(value, str) and value.startswith("custom:"):
        return CustomWorkMode(value, label)
    try:
        return WorkMode(value) if value is not None else None
    except (ValueError, TypeError):
        raise ValueError("work_mode_invalid") from None


@dataclass(frozen=True)
class CustomEntryType:
    value: str
    label: str
    category: str = "work"
    revision: int = 0
    archived: bool = False

    def __post_init__(self):
        _validate_custom_definition(self.value, self.label, "entry_type_invalid")
        if self.category not in {"work", "break", "leave"} or type(self.revision) is not int or self.revision < 0:
            raise ValueError("entry_type_invalid")
        object.__setattr__(self, "category", EntryCategory(self.category))


class EntryType(str, Enum):
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

    @property
    def category(self) -> EntryCategory:
        if self.value in LEAVE_TYPES:
            return EntryCategory.LEAVE
        return EntryCategory.BREAK if self == EntryType.BREAK else EntryCategory.WORK

    @property
    def is_legacy(self) -> bool:
        return self in {EntryType.REMOTE, EntryType.BUSINESS_TRIP}


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
    entry_type: EntryType | CustomEntryType = EntryType.NORMAL
    overnight: bool = False
    started_at: datetime | None = None
    ended_at: datetime | None = None
    id: int | None = None
    revision: int = 0
    capture_id: str | None = None
    entries: tuple[WorkLog, ...] = ()
    context: WorkContext = WorkContext()
    work_mode: WorkModeValue | None = None

    @property
    def has_times(self) -> bool:
        return bool(self.start_time and self.end_time)

    @property
    def is_note_only(self) -> bool:
        return not self.has_times and self.entry_type == EntryType.NORMAL and self.break_hours == 0 and bool(self.note)

    @property
    def is_leave(self) -> bool:
        if self.entries:
            return all(entry.is_leave for entry in self.entries)
        from worklogger.domain.worklog.rules import normalize_entry_type

        return normalize_entry_type(self.entry_type).category == EntryCategory.LEAVE

    @property
    def is_break(self) -> bool:
        if self.entries:
            return all(entry.is_break for entry in self.entries)
        from worklogger.domain.worklog.rules import normalize_entry_type

        return normalize_entry_type(self.entry_type).category == EntryCategory.BREAK

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
        return raw if raw > 0 else max(float(DEFAULT_LEAVE_HOURS if standard_hours is None else standard_hours), 0.0)

    def classified_hours(self, *, standard_leave_hours: float = DEFAULT_LEAVE_HOURS) -> float:
        """Return classified duration without treating break or leave as work."""
        if self.entries:
            return sum(entry.classified_hours(standard_leave_hours=standard_leave_hours) for entry in self.entries)
        if self.is_leave:
            return self.leave_hours(standard_hours=standard_leave_hours)
        return self.raw_hours() if self.is_break else self.worked_hours()
