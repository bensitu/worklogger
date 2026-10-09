"""Analytics data preparation rules."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from collections.abc import Callable, Iterable, Sequence

from worklogger.config.constants import DEFAULT_LEAVE_HOURS
from worklogger.domain.analytics.models import AnalyticsDashboard, ChartDataBundle, MonthStats
from worklogger.domain.worklog.models import WorkLog, WorkType
from worklogger.domain.reporting.periods import weekly_period


def month_stats(month_rows: Iterable[WorkLog], standard_work_hours: float) -> MonthStats:
    month_rows = tuple(month_rows)
    rest_dates = {entry.day for record in month_rows for entry in (record.entries or (record,))
                  if entry.work_type == WorkType.BREAK and entry.raw_hours() > 0}
    total = 0.0
    overtime = 0.0
    work_days = 0
    leave_days = 0
    for record in month_rows:
        if record.leave_hours(standard_hours=standard_work_hours) > 0:
            leave_days += 1
        if record.is_leave:
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
        rest_days=len(rest_dates),
    )


def analytics_period(year: int, month: int, scope: str) -> tuple[date, date]:
    date(year, month, 1)
    if scope == "monthly":
        start_month, end_month = month, month
    elif scope == "quarterly":
        start_month = ((month - 1) // 3) * 3 + 1
        end_month = start_month + 2
    elif scope == "annual":
        start_month, end_month = 1, 12
    else:
        raise ValueError("analytics_scope_invalid")
    return date(year, start_month, 1), date(year, end_month, monthrange(year, end_month)[1])


def dashboard_data(
    records: Sequence[WorkLog],
    *,
    year: int,
    month: int,
    scope: str,
    standard_hours: float,
    monthly_target: float,
    week_start_monday: bool = False,
) -> AnalyticsDashboard:
    start, end = analytics_period(year, month, scope)
    month_count = end.month - start.month + 1
    previous_end = start - timedelta(days=1)
    previous_index = start.year * 12 + start.month - 1 - month_count
    previous_start = date(previous_index // 12, previous_index % 12 + 1, 1)
    current = tuple(row for row in records if start <= row.day <= end)
    previous = tuple(row for row in records if previous_start <= row.day <= previous_end)
    stats = month_stats(current, standard_hours)

    if scope == "monthly":
        by_day = {row.day: row for row in current}
        trend = monthly_chart_data(start, end, "hours", True, by_day.get, standard_leave_hours=standard_hours, week_start_monday=week_start_monday)
        average = monthly_chart_data(start, end, "average", True, by_day.get, standard_leave_hours=standard_hours, week_start_monday=week_start_monday)
    else:
        labels, totals, counts, leaves, leave_counts = [], [], [], [], []
        for selected_month in range(start.month, end.month + 1):
            rows = tuple(row for row in current if row.day.month == selected_month)
            summary = month_stats(rows, standard_hours)
            labels.append(f"{selected_month:02d}")
            totals.append(summary.total_hours)
            counts.append(summary.work_days)
            leaves.append(sum(row.leave_hours(standard_hours=standard_hours) for row in rows))
            leave_counts.append(summary.leave_days)
        trend = _bundle(labels, totals, counts, leaves, leave_counts, "hours", True)
        average = _bundle(labels, totals, counts, leaves, leave_counts, "average", True)

    modes: dict[str, float] = {}
    for row in (entry for record in current for entry in (record.entries or (record,))):
        key = "leave" if row.is_leave else row.work_type.value
        hours = row.leave_hours(standard_hours=standard_hours) if row.is_leave else row.worked_hours()
        if hours > 0:
            modes[key] = modes.get(key, 0.0) + hours

    daily = []
    if scope == "quarterly":
        year_rows = tuple(row for row in records if row.day.year == year)
        for quarter in range(1, 5):
            rows = tuple(row for row in year_rows if (row.day.month - 1) // 3 + 1 == quarter)
            daily.append((f"Q{quarter}", month_stats(rows, standard_hours).average_hours))
    else:
        last_month_index = end.year * 12 + end.month - 1
        first_month_index = last_month_index - 5 if scope == "monthly" else year * 12
        for index in range(first_month_index, last_month_index + 1):
            selected_year, selected_month = index // 12, index % 12 + 1
            rows = tuple(row for row in records if row.day.year == selected_year and row.day.month == selected_month)
            daily.append((f"{selected_month:02d}", month_stats(rows, standard_hours).average_hours))
    return AnalyticsDashboard(
        start, end, stats, month_stats(previous, standard_hours), monthly_target * month_count,
        (end - start).days + 1, (previous_end - previous_start).days + 1,
        trend, average, tuple(modes.items()), ChartDataBundle(tuple(daily), tuple(daily), frozenset(), (), ()),
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
    week_start_monday: bool = False,
) -> ChartDataBundle:
    if end < start:
        return ChartDataBundle((), (), frozenset(), (), ())

    first_weekday, days = monthrange(start.year, start.month)
    first = first_weekday if week_start_monday else (first_weekday + 1) % 7
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
    week_start_monday: bool = False,
) -> ChartDataBundle:
    labels = [f"Q{quarter}" for quarter in range(1, 5)]
    totals = [0.0 for _label in labels]
    unit_sets: list[set[date]] = [set() for _label in labels]
    leave_hours = [0.0 for _label in labels]
    leave_unit_sets: list[set[date]] = [set() for _label in labels]

    for month in range(1, 13):
        quarter_index = (month - 1) // 3
        for record in month_records_getter(month):
            hours = record.worked_hours()
            if hours > 0:
                totals[quarter_index] += hours
                unit_sets[quarter_index].add(weekly_period(record.day, week_start_monday).start)
            leave_value = record.leave_hours(standard_hours=standard_leave_hours)
            if leave_value > 0:
                leave_hours[quarter_index] += leave_value
                leave_unit_sets[quarter_index].add(weekly_period(record.day, week_start_monday).start)

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
