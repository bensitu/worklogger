from __future__ import annotations
import csv
from dataclasses import dataclass
from datetime import date, timedelta
from config.constants import DEFAULT_LEAVE_HOURS
from core.time_calc import calc_hours


@dataclass(frozen=True)
class ChartDataBundle:
    bar_data: list[tuple[str, float]]
    line_data: list[tuple[str, float]]
    leave_indices: set[int]
    leave_line_data: list[float | None]
    leave_hours_data: list[tuple[str, float]]


def month_stats(month_rows: list, work_hours: float):
    """Return (total_h, ot_h, work_days, leave_days, avg_h) for *month_rows*."""
    total = ot = 0.0
    wd = ld = 0
    for r in month_rows:
        if r.is_leave:
            ld += 1
            continue
        if r.has_times:
            h = calc_hours(r.start, r.end, r.break_hours)
            if h > 0:
                total += h
                ot += max(h - work_hours, 0)
                wd += 1
    return total, ot, wd, ld, total / wd if wd else 0.0


def _raw_record_hours(rec) -> float:
    if rec and rec.has_times:
        return calc_hours(rec.start, rec.end, rec.break_hours)
    return 0.0


def _work_hours(rec) -> float:
    if rec and rec.is_leave:
        return 0.0
    return _raw_record_hours(rec)


def _leave_hours(rec, standard_hours: float) -> float:
    if not rec or not rec.is_leave:
        return 0.0
    hours = _raw_record_hours(rec)
    if hours > 0:
        return hours
    return max(float(standard_hours or DEFAULT_LEAVE_HOURS), 0.0)


def _metric_value(total_hours: float, unit_count: int, metric: str) -> float:
    if metric == "average":
        return total_hours / unit_count if unit_count else 0.0
    return total_hours


def _bundle(
    labels: list[str],
    totals: list[float],
    unit_counts: list[int],
    leave_hours: list[float],
    leave_unit_counts: list[int],
    metric: str,
    include_leaves: bool,
) -> ChartDataBundle:
    values = [
        _metric_value(total, units, metric)
        for total, units in zip(totals, unit_counts)
    ]
    leave_values = [
        _metric_value(total, units, metric)
        for total, units in zip(leave_hours, leave_unit_counts)
    ]
    leave_indices = {i for i, hours in enumerate(leave_values) if include_leaves and hours > 0}
    leave_line_data = [
        hours if include_leaves and hours > 0 else None
        for hours in leave_values
    ]
    data = list(zip(labels, values))
    return ChartDataBundle(
        bar_data=data,
        line_data=data,
        leave_indices=leave_indices,
        leave_line_data=leave_line_data,
        leave_hours_data=list(zip(labels, leave_values)),
    )


def monthly_chart_data_v3(
    start: date,
    end: date,
    metric: str,
    include_leaves: bool,
    record_getter,
    standard_hours: float = DEFAULT_LEAVE_HOURS,
) -> ChartDataBundle:
    if end < start:
        return ChartDataBundle([], [], set(), [], [])
    from calendar import monthrange
    first, days = monthrange(start.year, start.month)
    first = (first + 1) % 7
    max_r = (days + first - 1) // 7
    labels = [f"W{r + 1}" for r in range(max_r + 1)]
    totals = [0.0 for _label in labels]
    unit_counts = [0 for _label in labels]
    leave_hours = [0.0 for _label in labels]
    leave_unit_counts = [0 for _label in labels]
    cur = start
    while cur <= end:
        row = (cur.day + first - 1) // 7
        if 0 <= row < len(labels):
            rec = record_getter(cur.isoformat())
            hours = _work_hours(rec)
            if hours > 0:
                totals[row] += hours
                unit_counts[row] += 1
            leave_value = _leave_hours(rec, standard_hours)
            if leave_value > 0:
                leave_hours[row] += leave_value
                leave_unit_counts[row] += 1
        cur += timedelta(days=1)
    return _bundle(labels, totals, unit_counts, leave_hours, leave_unit_counts, metric, include_leaves)


def quarterly_chart_data_v3(
    month_records_getter,
    y: int,
    metric: str,
    include_leaves: bool,
    standard_hours: float = DEFAULT_LEAVE_HOURS,
) -> ChartDataBundle:
    labels = [f"Q{q}" for q in range(1, 5)]
    totals = [0.0 for _label in labels]
    unit_sets: list[set[tuple[int, int]]] = [set() for _label in labels]
    leave_hours = [0.0 for _label in labels]
    leave_unit_sets: list[set[tuple[int, int]]] = [set() for _label in labels]
    for month in range(1, 13):
        q_idx = (month - 1) // 3
        for rec in month_records_getter(f"{y}-{month:02d}"):
            hours = _work_hours(rec)
            if hours > 0:
                totals[q_idx] += hours
                d = date.fromisoformat(rec.date)
                iso = d.isocalendar()
                unit_sets[q_idx].add((iso.year, iso.week))
            leave_value = _leave_hours(rec, standard_hours)
            if leave_value > 0:
                leave_hours[q_idx] += leave_value
                d = date.fromisoformat(rec.date)
                iso = d.isocalendar()
                leave_unit_sets[q_idx].add((iso.year, iso.week))
    unit_counts = [len(units) for units in unit_sets]
    leave_unit_counts = [len(units) for units in leave_unit_sets]
    return _bundle(labels, totals, unit_counts, leave_hours, leave_unit_counts, metric, include_leaves)


def annual_chart_data_v3(
    month_records_getter,
    y: int,
    month_short: list[str],
    metric: str,
    include_leaves: bool,
    standard_hours: float = DEFAULT_LEAVE_HOURS,
) -> ChartDataBundle:
    labels = [month_short[m - 1] for m in range(1, 13)]
    totals = [0.0 for _label in labels]
    unit_counts = [0 for _label in labels]
    leave_hours = [0.0 for _label in labels]
    leave_unit_counts = [0 for _label in labels]
    for month in range(1, 13):
        idx = month - 1
        for rec in month_records_getter(f"{y}-{month:02d}"):
            hours = _work_hours(rec)
            if hours > 0:
                totals[idx] += hours
                unit_counts[idx] += 1
            leave_value = _leave_hours(rec, standard_hours)
            if leave_value > 0:
                leave_hours[idx] += leave_value
                leave_unit_counts[idx] += 1
    return _bundle(labels, totals, unit_counts, leave_hours, leave_unit_counts, metric, include_leaves)


def export_chart_csv(
    path: str,
    bundle: ChartDataBundle,
    period_header: str,
    value_header: str,
    leave_hours_header: str,
) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([period_header, value_header, leave_hours_header])
        leave_by_label = dict(bundle.leave_hours_data)
        for label, value in bundle.bar_data:
            writer.writerow([label, f"{value:.2f}", f"{leave_by_label.get(label, 0.0):.2f}"])
