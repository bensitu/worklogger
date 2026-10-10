"""Project accounting based on saved individual-record classifications."""

from __future__ import annotations

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
    children: tuple[ContextSummary, ...] = ()


def context_summaries(entries, standard_hours=8.0):
    groups = {}
    project_days = {}
    for entry in entries:
        context = entry.context
        key = (("id", context.project_id) if context.project_id else ("label", context.project_label),
               ("id", context.work_item_id) if context.work_item_id else ("label", context.work_item_label))
        group = groups.setdefault(key, [context, 0.0, 0.0, 0.0, set(), 0])
        group[0] = context
        hours = entry.worked_hours()
        group[1] += hours
        group[2] += entry.raw_hours() if entry.is_break else entry.break_hours
        group[3] += entry.leave_hours(standard_hours=standard_hours)
        if hours > 0:
            group[4].add(entry.day)
            project_days.setdefault(key[0], set()).add(entry.day)
        group[5] += 1
    projects = {}
    for key, (context, work, rest, leave, days, count) in groups.items():
        projects.setdefault(key[0], []).append(ContextSummary(context, work, rest, leave, len(days), count))
    summaries = []
    for key, children in projects.items():
        context = children[-1].context
        summaries.append(ContextSummary(WorkContext(context.project_id, None, context.project_label),
            sum(child.work_hours for child in children), sum(child.rest_hours for child in children),
            sum(child.leave_hours for child in children), len(project_days.get(key, ())),
            sum(child.record_count for child in children), tuple(sorted(children, key=lambda child: child.context.work_item_label.casefold()))))
    return tuple(sorted(summaries, key=lambda group: group.context.project_label.casefold()))
