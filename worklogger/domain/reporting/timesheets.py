"""Deterministic recorded-time snapshots for editable and printed delivery."""

from dataclasses import dataclass
from datetime import date, datetime
import math

from worklogger.domain.worklog.models import WorkLog
from worklogger.domain.worklog.rules import aggregate_days
from worklogger.domain.analytics.rules import month_stats

MAX_TIMESHEET_ENTRIES = 50_000
MAX_TIMESHEET_TEXT_CHARACTERS = 2_000_000


@dataclass(frozen=True)
class Timesheet:
    start: date
    end: date
    author: str
    generated_at: datetime
    standard_hours: float
    entries: tuple[WorkLog, ...]

    def __post_init__(self):
        if (self.end < self.start or (self.end - self.start).days > 366
                or self.generated_at.tzinfo is None or not math.isfinite(self.standard_hours)
                or not 1 <= self.standard_hours <= 24):
            raise ValueError("timesheet_invalid")
        if (len(self.entries) > MAX_TIMESHEET_ENTRIES
                or sum(len(entry.note) + len(entry.context.label) for entry in self.entries) > MAX_TIMESHEET_TEXT_CHARACTERS):
            raise ValueError("timesheet_too_large")
        if any(entry.day < self.start or entry.day > self.end or entry.entries for entry in self.entries):
            raise ValueError("timesheet_invalid")

    @property
    def statistics(self):
        return month_stats(aggregate_days(self.entries), self.standard_hours)

    @property
    def rest_hours(self):
        return sum(entry.raw_hours() if entry.is_break else entry.break_hours for entry in self.entries)

    @property
    def leave_hours(self):
        return sum(entry.leave_hours(standard_hours=self.standard_hours) for entry in self.entries)

    def record_status(self, entry):
        if entry.ended_at is not None:
            return "scheduled" if entry.ended_at > self.generated_at else "recorded"
        if entry.day > self.generated_at.date():
            return "scheduled"
        return "historical"
