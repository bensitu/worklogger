"""Project accounting based on saved individual-record classifications."""

from dataclasses import dataclass
from worklogger.domain.projects.models import WorkContext


@dataclass(frozen=True)
class ContextSummary:
    context: WorkContext
    work_hours: float
    rest_hours: float
    leave_hours: float
    work_days: int
    record_count: int


def context_summaries(entries, standard_hours=8.0):
    groups = {}
    for entry in entries:
        context = entry.context
        key = (context.project_id or context.project_label, context.work_item_id or context.work_item_label)
        group = groups.setdefault(key, [context, 0.0, 0.0, 0.0, set(), 0])
        group[0] = context
        hours = entry.worked_hours()
        group[1] += hours
        group[2] += entry.raw_hours() if entry.is_break else entry.break_hours
        group[3] += entry.leave_hours(standard_hours=standard_hours)
        if hours > 0:
            group[4].add(entry.day)
        group[5] += 1
    return tuple(ContextSummary(context, work, rest, leave, len(days), count)
                 for context, work, rest, leave, days, count in sorted(groups.values(), key=lambda value: value[0].label.casefold()))
