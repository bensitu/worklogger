"""Weekly and monthly report generation."""

from __future__ import annotations
import datetime as _dt
from calendar import monthrange
from typing import TYPE_CHECKING

from core.time_calc import calc_hours
from utils.i18n import _, msg

if TYPE_CHECKING:
    from data.db import DB


def _wt_label(wt: str) -> str:
    mapping = {
        "normal": "wt_normal", "remote": "wt_remote",
        "business_trip": "wt_business", "paid_leave": "wt_paid",
        "comp_leave": "wt_comp", "sick_leave": "wt_sick",
    }
    fallback = {
        "wt_normal": "Normal",
        "wt_remote": "Remote work",
        "wt_business": "Business trip",
        "wt_paid": "Paid leave",
        "wt_comp": "Comp leave",
        "wt_sick": "Sick leave",
    }
    key = mapping.get(wt, "wt_normal")
    return msg(key, fallback.get(key, wt))


def _fmt_entry(dt: _dt.date, rec, work_hours: float,
               lang: str) -> tuple[str | None, float, float]:
    dow = [_("Sun"), _("Mon"), _("Tue"), _("Wed"), _("Thu"), _("Fri"), _("Sat")][(dt.weekday() + 1) % 7]
    if rec and rec.is_leave:
        h = calc_hours(rec.start, rec.end, rec.break_hours) if rec.has_times else 0.0
        hours = f"  {h:.1f}h" if h > 0 else ""
        overnight = f"  [{_("Night")}]" if rec.is_overnight and rec.has_times else ""
        note = f"\n  → {rec.note}" if rec.note else ""
        return (
            f"{dt.isoformat()}（{dow}）{hours} [{_wt_label(rec.safe_work_type())}]"
            f"{overnight}{note}",
            0.0,
            0.0,
        )
    if rec and rec.has_times:
        h = calc_hours(rec.start, rec.end, rec.break_hours)
        ot = max(h - work_hours, 0)
        wt = rec.safe_work_type()
        overnight = f"  [{_("Night")}]" if rec.is_overnight else ""
        ots = f"  OT+{ot:.1f}h" if ot > 0 else ""
        note = f"\n  → {rec.note}" if rec.note else ""
        line = _("{date}  ({dow})  {h}h  [{wt}]").format(
            date=dt.isoformat(), dow=dow,
            h=f"{h:.1f}", wt=_wt_label(wt))
        return line + overnight + ots + note, h, ot
    return None, 0.0, 0.0


def generate_weekly(
    selected: _dt.date,
    db: "DB",
    work_hours: float,
    lang: str,
    *,
    user_id: int,
    save_to_db: bool = False,
) -> str:
    monday = selected - _dt.timedelta(days=selected.weekday())
    sunday = monday + _dt.timedelta(days=6)
    header = _("Weekly Work Report  {start} – {end}").format(
        start=monday.isoformat(), end=sunday.isoformat())
    lines = [f"# {header}", ""]
    total = ot_total = days = 0.0
    for i in range(7):
        dt = monday + _dt.timedelta(days=i)
        rec = db.get(dt.isoformat(), user_id=user_id)
        line, h, ot = _fmt_entry(dt, rec, work_hours, lang)
        if line:
            lines.append(line)
            total += h
            ot_total += ot
            if h > 0:
                days += 1
    if days == 0:
        lines.append(_("No notes recorded for this period."))
    lines += ["", _("Summary: {days} work days, {total}h total, {ot}h overtime.").format(
        days=int(days), total=f"{total:.1f}", ot=f"{ot_total:.1f}")]
    content = "\n".join(lines)
    if save_to_db:
        db.save_report(
            "weekly",
            monday.isoformat(),
            sunday.isoformat(),
            content,
            user_id=user_id,
        )
    return content


def generate_monthly(
    year: int,
    month: int,
    db: "DB",
    work_hours: float,
    lang: str,
    *,
    user_id: int,
    save_to_db: bool = False,
) -> str:
    header = _("Monthly Work Report  {year}/{month:02d}").format(year=year, month=month)
    lines = [f"# {header}", ""]
    _first_weekday, days = monthrange(year, month)
    total = ot_total = n_days = 0.0
    recs = {r[0]: r for r in db.month(f"{year}-{month:02d}", user_id=user_id)}
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
        lines.append(_("No notes recorded for this period."))
    lines += ["", _("Summary: {days} work days, {total}h total, {ot}h overtime.").format(
        days=int(n_days), total=f"{total:.1f}", ot=f"{ot_total:.1f}")]
    content = "\n".join(lines)
    if save_to_db:
        db.save_report(
            "monthly",
            f"{year}-{month:02d}-01",
            f"{year}-{month:02d}-{days:02d}",
            content,
            user_id=user_id,
        )
    return content
