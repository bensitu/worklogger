"""Export and import services: CSV, ICS, PDF.

``parse_ics`` (the minimal single-field parser) was removed; all callers
should use ``calendar_service.parse_ics_rich`` which returns full event
data including time info.

``render_pdf`` now accepts ``PdfContext`` instead of the raw ``App``
widget, so the service layer has zero dependency on UI objects.
"""

from __future__ import annotations
import csv
import re
from dataclasses import dataclass
from datetime import datetime, date
from typing import TYPE_CHECKING

from core.time_calc import calc_hours, shift_datetimes

if TYPE_CHECKING:
    from data.db import DB


@dataclass(frozen=True)
class PdfContext:
    """All data ``render_pdf`` needs — no UI object references.

    Build one from ``AppStore.state`` in the UI layer before calling
    ``render_pdf``, so the service layer stays free of Qt widget imports.
    """
    lang: str
    theme: str
    dark: bool
    year: int
    month: int
    work_hours: float
    monthly_target: float


def export_csv(path: str, rows: list) -> None:
    # utf-8-sig writes a UTF-8 BOM so Windows Excel opens the file without
    # showing garbled characters for CJK content.
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["date", "start", "end", "break", "note", "work_type"])
        for r in rows:
            # Keep export schema stable even if internal record gains fields.
            w.writerow(list(r)[:6])


def import_csv(path: str, db: "DB", required_cols: set,
               default_break: float = 1.0) -> tuple[int, list[str]]:
    """Returns (imported_count, error_list)."""
    from config.constants import WORK_TYPE_KEYS
    errors: list[str] = []
    imported = 0
    # Accept both plain UTF-8 and UTF-8 with BOM.
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if not rows:
        raise ValueError("empty")
    raw_header = [h.strip().lower() for h in rows[0]]
    header = set(raw_header)
    normalized = {"break" if h == "lunch" else h for h in header}
    missing = required_cols - normalized
    if missing:
        raise ValueError(f"missing:{','.join(missing)}")
    idx_map = {name: i for i, name in enumerate(raw_header)}
    break_idx = idx_map.get("break", idx_map.get("lunch"))
    for i, row in enumerate(rows[1:], 2):
        try:
            if len(row) < 5:
                raise ValueError(f"only {len(row)} columns")
            d = row[idx_map["date"]]
            s = row[idx_map["start"]]
            e = row[idx_map["end"]]
            b = row[break_idx] if break_idx is not None and break_idx < len(
                row) else ""
            n = row[idx_map["note"]]
            wt_idx = idx_map.get("work_type")
            wt = row[wt_idx] if wt_idx is not None and wt_idx < len(
                row) and row[wt_idx] in WORK_TYPE_KEYS else "normal"
            datetime.strptime(d, "%Y-%m-%d")
            if s:
                datetime.strptime(s, "%H:%M")
            if e:
                datetime.strptime(e, "%H:%M")
            db.save(d, s or None, e or None, float(
                b) if b else default_break, n, wt)
            imported += 1
        except Exception as ex:
            errors.append(f"Row {i}: {ex}")
    return imported, errors


def build_ics(rows: list) -> str:
    """Build minimal iCalendar string from worklog rows."""
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//WorkLogger//WorkLogger//EN", "CALSCALE:GREGORIAN",
    ]
    for r in rows:
        if not r.has_times:
            continue
        h = calc_hours(r.start, r.end, r.break_hours)
        note = r.safe_note().replace("\\n", " ").replace(",", "\\,")
        summary = f"Work {h:.1f}h" + (f" — {note[:60]}" if note else "")
        dt_pair = shift_datetimes(r.date, r.start, r.end)
        if not dt_pair:
            continue
        start_dt, end_dt = dt_pair
        dtstart = start_dt.strftime("%Y%m%dT%H%M%S")
        dtend = end_dt.strftime("%Y%m%dT%H%M%S")
        lines += [
            "BEGIN:VEVENT",
            f"DTSTART:{dtstart}", f"DTEND:{dtend}",
            f"SUMMARY:{summary}", f"DESCRIPTION:{note[:500]}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def render_pdf(
    path: str,
    tab_index: int,
    tab_name: str,
    chart_widget,
    data: list,
    detail_fn,
    ctx: "PdfContext",
) -> None:
    """Render a full PDF report for the given analytics tab.

    Parameters
    ----------
    ctx:
        A :class:`PdfContext` data object.  Build it from ``AppStore.state``
        in the UI layer; this function has no dependency on Qt widget objects.
    """
    from PySide6.QtPrintSupport import QPrinter
    from PySide6.QtCore import QMarginsF, QRectF
    from PySide6.QtGui import (QPainter, QPageLayout, QPageSize,
                               QFont, QColor, QPen, QBrush)
    from PySide6.QtCore import Qt
    from utils.i18n import _
    from config.themes import THEMES
    from ui.widgets import BarChart
    acc = THEMES[ctx.theme][False][0]

    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(path)
    printer.setPageLayout(QPageLayout(
        QPageSize(QPageSize.A4), QPageLayout.Portrait,
        QMarginsF(12, 12, 12, 12), QPageLayout.Millimeter,
    ))
    painter = QPainter(printer)
    if not painter.isActive():
        raise RuntimeError("Could not start PDF painter")

    pr = printer.pageRect(QPrinter.DevicePixel)
    pw, ph = int(pr.width()), int(pr.height())
    dpi = printer.resolution()
    def pt(n): return int(n * dpi / 72)

    f = QFont("sans-serif")
    f.setPixelSize(pt(20))
    f.setBold(True)
    painter.setFont(f)
    painter.setPen(QColor("#1e2035"))
    th = pt(30)
    painter.drawText(QRectF(0, 0, pw, th),
                     Qt.AlignHCenter | Qt.AlignVCenter, _("Work Time Analytics"))
    f2 = QFont("sans-serif")
    f2.setPixelSize(pt(10))
    painter.setFont(f2)
    painter.setPen(QColor("#606888"))
    y, m = ctx.year, ctx.month
    sub = (f"{tab_name}  —  {y}/{m:02d}" if tab_index == 0
           else f"{tab_name}  —  {y}")
    sh = pt(20)
    painter.drawText(QRectF(0, th, pw, sh),
                     Qt.AlignHCenter | Qt.AlignVCenter, sub)
    sep_y = th + sh + pt(4)
    painter.setPen(QPen(QColor("#d0d8e8"), pt(1)))
    painter.drawLine(int(pw*0.03), sep_y, int(pw*0.97), sep_y)
    cursor_y = sep_y + pt(6)

    mt = ctx.monthly_target
    refs = [mt / 4.3, mt * 3, mt]
    tmp = BarChart(data, ref=refs[tab_index], dark=False, accent=acc,
                   unit=_("h"), no_data=_("No data"))
    tmp.resize(chart_widget.size())
    src_px = tmp.grab()
    tmp.deleteLater()
    tw = pw
    th_img = int(src_px.height() * pw / src_px.width())
    if th_img > int(ph * 0.38):
        th_img = int(ph * 0.38)
        tw = int(src_px.width() * th_img / src_px.height())
    scaled = src_px.scaled(tw*2, th_img*2, Qt.KeepAspectRatio,
                           Qt.SmoothTransformation)
    cx = (pw - tw) // 2
    painter.drawPixmap(QRectF(cx, cursor_y, tw, th_img), scaled,
                       QRectF(scaled.rect()))
    cursor_y += th_img + pt(8)

    painter.setPen(QPen(QColor("#d0d8e8"), pt(1)))
    painter.drawLine(int(pw*0.03), cursor_y, int(pw*0.97), cursor_y)
    cursor_y += pt(10)

    detail_fn(painter, pw, ph, pt, _, cursor_y, ctx)
    painter.end()
