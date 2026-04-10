"""Weekly and monthly report generation."""

from __future__ import annotations
import datetime as _dt
from calendar import monthrange
from typing import TYPE_CHECKING

from core.time_calc import calc_hours
from config.constants import LEAVE_TYPES
from config.i18n import T

if TYPE_CHECKING:
    from data.db import DB


def _wt_label(wt: str, t: dict) -> str:
    mapping = {
        "normal": "wt_normal", "remote": "wt_remote",
        "business_trip": "wt_business", "paid_leave": "wt_paid",
        "comp_leave": "wt_comp", "sick_leave": "wt_sick",
    }
    return t.get(mapping.get(wt, "wt_normal"), wt)


def _fmt_entry(dt: _dt.date, rec, work_hours: float,
               lang: str) -> tuple[str | None, float, float]:
    t = T[lang]
    dow = t["days"][(dt.weekday() + 1) % 7]
    if rec and rec.has_times:
        h = calc_hours(rec.start, rec.end, rec.break_hours)
        ot = max(h - work_hours, 0)
        wt = rec.safe_work_type()
        ots = f"  OT+{ot:.1f}h" if ot > 0 else ""
        note = f"\n  → {rec.note}" if rec.note else ""
        line = t["report_day_line"].format(
            date=dt.isoformat(), dow=dow,
            h=f"{h:.1f}", wt=_wt_label(wt, t))
        return line + ots + note, h, ot
    elif rec and rec.is_leave:
        note = f"\n  → {rec.note}" if rec.note else ""
        return (f"{dt.isoformat()}（{dow}）[{_wt_label(rec.safe_work_type(), t)}]{note}",
                0.0, 0.0)
    return None, 0.0, 0.0


def generate_weekly(
    selected: _dt.date,
    db: "DB",
    work_hours: float,
    lang: str,
) -> str:
    t = T[lang]
    monday = selected - _dt.timedelta(days=selected.weekday())
    sunday = monday + _dt.timedelta(days=6)
    header = t["week_report_header"].format(
        start=monday.isoformat(), end=sunday.isoformat())
    lines = [f"# {header}", ""]
    total = ot_total = days = 0.0
    for i in range(7):
        dt = monday + _dt.timedelta(days=i)
        rec = db.get(dt.isoformat())
        line, h, ot = _fmt_entry(dt, rec, work_hours, lang)
        if line:
            lines.append(line)
            total += h
            ot_total += ot
            if h > 0:
                days += 1
    if days == 0:
        lines.append(t["report_no_notes"])
    lines += ["", t["report_summary"].format(
        days=int(days), total=f"{total:.1f}", ot=f"{ot_total:.1f}")]
    return "\n".join(lines)


def generate_monthly(
    year: int,
    month: int,
    db: "DB",
    work_hours: float,
    lang: str,
) -> str:
    t = T[lang]
    header = t["month_report_header"].format(year=year, month=month)
    lines = [f"# {header}", ""]
    _, days = monthrange(year, month)
    total = ot_total = n_days = 0.0
    recs = {r[0]: r for r in db.month(f"{year}-{month:02d}")}
    for d in range(1, days + 1):
        dt = _dt.date(year, month, d)
        rec = recs.get(dt.isoformat())
        line, h, ot = _fmt_entry(dt, rec, work_hours, lang)
        if line:
            lines.append(line)
            total += h
            ot_total += ot
            if h > 0:
                n_days += 1
    if n_days == 0:
        lines.append(t["report_no_notes"])
    lines += ["", t["report_summary"].format(
        days=int(n_days), total=f"{total:.1f}", ot=f"{ot_total:.1f}")]
    return "\n".join(lines)
