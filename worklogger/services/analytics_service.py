from __future__ import annotations
from datetime import date
from core.time_calc import calc_hours


def month_stats(month_rows: list, work_hours: float):
    """Return (total_h, ot_h, work_days, leave_days, avg_h) for *month_rows*."""
    total = ot = 0.0
    wd = ld = 0
    for r in month_rows:
        if r.has_times:
            h = calc_hours(r.start, r.end, r.break_hours)
            if h > 0:
                total += h
                ot += max(h - work_hours, 0)
                wd += 1
        if r.is_leave:
            ld += 1
    return total, ot, wd, ld, total / wd if wd else 0.0


def monthly_chart_data(record_getter, y: int, m: int):
    from calendar import monthrange
    first, days = monthrange(y, m)
    first = (first + 1) % 7
    weekly: dict[int, float] = {}
    for d in range(1, days + 1):
        row = (d + first - 1) // 7
        rec = record_getter(date(y, m, d).isoformat())
        if rec and rec.has_times:
            weekly[row] = weekly.get(row, 0.0) + calc_hours(rec.start, rec.end, rec.break_hours)
    max_r = (days + first - 1) // 7
    return [(f"W{r+1}", weekly.get(r, 0.0)) for r in range(max_r + 1)]


def quarter_hours(month_records_getter, y: int):
    return [(f"Q{q}", sum(
        sum(calc_hours(r.start, r.end, r.break_hours)
            for r in month_records_getter(f"{y}-{m:02d}") if r.has_times)
        for m in range((q - 1) * 3 + 1, q * 3 + 1)))
        for q in range(1, 5)]


def annual_hours(month_records_getter, y: int, month_short: list[str]):
    return [(month_short[m - 1],
             sum(calc_hours(r.start, r.end, r.break_hours)
                 for r in month_records_getter(f"{y}-{m:02d}") if r.has_times))
            for m in range(1, 13)]
