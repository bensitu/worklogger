"""Immutable classification allocations, independent of calendar drawing."""

from dataclasses import dataclass
from enum import StrEnum
import math
from collections.abc import Iterable

from worklogger.config.constants import DEFAULT_LEAVE_HOURS, ENTRY_TYPE_KEYS
from worklogger.domain.worklog.models import EntryCategory, WorkLog, WorkMode


class CalendarDimension(StrEnum):
    ENTRY_TYPE = "entry_type"
    WORK_MODE = "work_mode"


@dataclass(frozen=True)
class AllocationSegment:
    """Contributed duration in hours and a stable semantic color identifier."""

    key: str
    duration: float
    semantic_color_id: str
    category: EntryCategory = EntryCategory.WORK


def allocation_segments(records: Iterable[WorkLog], *, dimension: CalendarDimension = CalendarDimension.ENTRY_TYPE,
                        standard_leave_hours: float = DEFAULT_LEAVE_HOURS) -> tuple[AllocationSegment, ...]:
    dimension = CalendarDimension(dimension)
    totals: dict[tuple[str, EntryCategory], float] = {}
    for record in records:
        for entry in record.entries or (record,):
            if dimension == CalendarDimension.WORK_MODE:
                if entry.entry_type.category != EntryCategory.WORK:
                    continue
                key = entry.work_mode.value if entry.work_mode else "unspecified"
                hours = entry.worked_hours()
            else:
                key = entry.entry_type.value
                hours = entry.classified_hours(standard_leave_hours=standard_leave_hours)
            if math.isfinite(hours) and hours > 0:
                category = entry.entry_type.category if dimension == CalendarDimension.ENTRY_TYPE else EntryCategory.WORK
                identity = key, category
                totals[identity] = totals.get(identity, 0) + hours
    order = ENTRY_TYPE_KEYS if dimension == CalendarDimension.ENTRY_TYPE else (*[mode.value for mode in WorkMode], "unspecified")
    positions = {key: index for index, key in enumerate(order)}
    mode_colors = {"onsite": "normal", "remote": "remote", "business_trip": "business_trip",
                   "other": "other", "unspecified": "normal"}
    return tuple(AllocationSegment(key, totals[(key, category)], key if dimension == CalendarDimension.ENTRY_TYPE else mode_colors.get(key, key), category)
                 for key, category in sorted(totals, key=lambda identity: (positions.get(identity[0], len(positions)), *identity)))
