"""Analytics data preparation rules."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from collections.abc import Callable, Iterable, Sequence

from worklogger.config.constants import DEFAULT_LEAVE_HOURS
from worklogger.domain.analytics.models import ChartDataBundle, MonthStats
from worklogger.domain.worklog.models import WorkLog


def month_stats(month_rows: Iterable[WorkLog], standard_work_hours: float) -> MonthStats:
    total = 0.0
    overtime = 0.0
    work_days = 0
    leave_days = 0
    for record in month_rows:
        if record.is_leave:
            leave_days += 1
            continue
        hours = record.worked_hours()
        if hours > 0:
            total += hours
            overtime += max(hours - float(standard_work_hours), 0.0)
            work_days += 1
    return MonthStats(
        total_hours=total,
        overtime_hours=overtime,
        work_days=work_days,
        leave_days=leave_days,
        average_hours=total / work_days if work_days else 0.0,
    )


def _metric_value(total_hours: float, unit_count: int, metric: str) -> float:
    if metric == "average":
        return total_hours / unit_count if unit_count else 0.0
    return total_hours


def _bundle(
    labels: Sequence[str],
    totals: Sequence[float],
    unit_counts: Sequence[int],
    leave_hours: Sequence[float],
    leave_unit_counts: Sequence[int],
    metric: str,
    include_leaves: bool,
) -> ChartDataBundle:
    values = tuple(
        _metric_value(total, units, metric)
        for total, units in zip(totals, unit_counts)
    )
    leave_values = tuple(
        _metric_value(total, units, metric)
        for total, units in zip(leave_hours, leave_unit_counts)
    )
    leave_indices = frozenset(
        index
        for index, hours in enumerate(leave_values)
        if include_leaves and hours > 0
    )
    leave_line_data = tuple(
        hours if include_leaves and hours > 0 else None
        for hours in leave_values
    )
    bar_data = tuple(zip(labels, values))
    return ChartDataBundle(
        bar_data=bar_data,
        line_data=bar_data,
        leave_indices=leave_indices,
        leave_line_data=leave_line_data,
        leave_hours_data=tuple(zip(labels, leave_values)),
    )


def monthly_chart_data(
    start: date,
    end: date,
    metric: str,
    include_leaves: bool,
    record_getter: Callable[[date], WorkLog | None],
    *,
    standard_leave_hours: float = DEFAULT_LEAVE_HOURS,
) -> ChartDataBundle:
    if end < start:
        return ChartDataBundle((), (), frozenset(), (), ())

    first_weekday, days = monthrange(start.year, start.month)
    first = (first_weekday + 1) % 7
    max_row = (days + first - 1) // 7
    labels = [f"W{row + 1}" for row in range(max_row + 1)]
    totals = [0.0 for _label in labels]
    unit_counts = [0 for _label in labels]
    leave_hours = [0.0 for _label in labels]
    leave_unit_counts = [0 for _label in labels]

    current = start
    while current <= end:
        row = (current.day + first - 1) // 7
        if 0 <= row < len(labels):
            record = record_getter(current)
            if record:
                hours = record.worked_hours()
                if hours > 0:
                    totals[row] += hours
                    unit_counts[row] += 1
                leave_value = record.leave_hours(standard_hours=standard_leave_hours)
                if leave_value > 0:
                    leave_hours[row] += leave_value
                    leave_unit_counts[row] += 1
        current += timedelta(days=1)

    return _bundle(
        labels,
        totals,
        unit_counts,
        leave_hours,
        leave_unit_counts,
        metric,
        include_leaves,
    )


def quarterly_chart_data(
    month_records_getter: Callable[[int], Iterable[WorkLog]],
    year: int,
    metric: str,
    include_leaves: bool,
    *,
    standard_leave_hours: float = DEFAULT_LEAVE_HOURS,
) -> ChartDataBundle:
    labels = [f"Q{quarter}" for quarter in range(1, 5)]
    totals = [0.0 for _label in labels]
    unit_sets: list[set[tuple[int, int]]] = [set() for _label in labels]
    leave_hours = [0.0 for _label in labels]
    leave_unit_sets: list[set[tuple[int, int]]] = [set() for _label in labels]

    for month in range(1, 13):
        quarter_index = (month - 1) // 3
        for record in month_records_getter(month):
            hours = record.worked_hours()
            if hours > 0:
                totals[quarter_index] += hours
                iso = record.day.isocalendar()
                unit_sets[quarter_index].add((iso.year, iso.week))
            leave_value = record.leave_hours(standard_hours=standard_leave_hours)
            if leave_value > 0:
                leave_hours[quarter_index] += leave_value
                iso = record.day.isocalendar()
                leave_unit_sets[quarter_index].add((iso.year, iso.week))

    return _bundle(
        labels,
        totals,
        [len(units) for units in unit_sets],
        leave_hours,
        [len(units) for units in leave_unit_sets],
        metric,
        include_leaves,
    )


def annual_chart_data(
    month_records_getter: Callable[[int], Iterable[WorkLog]],
    year: int,
    month_labels: Sequence[str],
    metric: str,
    include_leaves: bool,
    *,
    standard_leave_hours: float = DEFAULT_LEAVE_HOURS,
) -> ChartDataBundle:
    labels = list(month_labels)
    if len(labels) != 12:
        raise ValueError("month_labels_required")
    totals = [0.0 for _label in labels]
    unit_counts = [0 for _label in labels]
    leave_hours = [0.0 for _label in labels]
    leave_unit_counts = [0 for _label in labels]

    for month in range(1, 13):
        index = month - 1
        for record in month_records_getter(month):
            hours = record.worked_hours()
            if hours > 0:
                totals[index] += hours
                unit_counts[index] += 1
            leave_value = record.leave_hours(standard_hours=standard_leave_hours)
            if leave_value > 0:
                leave_hours[index] += leave_value
                leave_unit_counts[index] += 1

    return _bundle(
        labels,
        totals,
        unit_counts,
        leave_hours,
        leave_unit_counts,
        metric,
        include_leaves,
    )
