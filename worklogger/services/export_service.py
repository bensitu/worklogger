"""Export and import services: CSV, ICS, PDF.

Calendar parsing is delegated to ``calendar_service.parse_ics_rich`` so
event time information is preserved consistently across imports.

``render_pdf`` accepts a ``PdfContext`` data object to keep this service
layer independent from UI widget classes.
"""

from __future__ import annotations
import csv
import re
from dataclasses import dataclass
from datetime import datetime, timezone
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


@dataclass(frozen=True)
class PdfColors:
    page_bg: str
    text: str
    muted: str
    separator: str
    panel_bg: str
    panel_header_bg: str
    row_bg: str
    row_alt_bg: str
    disabled: str
    accent: str


def pdf_colors(ctx: "PdfContext") -> PdfColors:
    """Return theme-aware PDF colors."""
    from config.themes import theme_colors

    accent, _hover, accent_dim, stat_bg, stat_border = theme_colors(
        ctx.theme,
        ctx.dark,
    )
    if ctx.dark:
        return PdfColors(
            page_bg="#151722",
            text="#eef2ff",
            muted="#a8b0ce",
            separator=stat_border,
            panel_bg=stat_bg,
            panel_header_bg=stat_border,
            row_bg="#161923",
            row_alt_bg="#1d2030",
            disabled="#707894",
            accent=accent,
        )
    return PdfColors(
        page_bg="#ffffff",
        text="#1e2035",
        muted="#606888",
        separator=stat_border,
        panel_bg=stat_bg,
        panel_header_bg=accent_dim,
        row_bg="#ffffff",
        row_alt_bg="#f7f9ff",
        disabled="#9090a8",
        accent=accent,
    )


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
               default_break: float = 1.0,
               *,
               user_id: int) -> tuple[int, list[str]]:
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
            db.save(
                d, s or None, e or None,
                float(b) if b else default_break,
                n,
                wt,
                user_id=user_id,
            )
            imported += 1
        except Exception as ex:
            errors.append(f"Row {i}: {ex}")
    return imported, errors


def _escape_ics_text(value: str) -> str:
    text = str(value or "")
    text = text.replace("\\", "\\\\")
    text = text.replace(";", "\\;")
    text = text.replace(",", "\\,")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("\n", "\\n")


def _fold_ics_line(line: str) -> list[str]:
    folded: list[str] = []
    current = ""
    current_len = 0
    for char in line:
        char_len = len(char.encode("utf-8"))
        if current and current_len + char_len > 75:
            folded.append(current)
            current = " " + char
            current_len = 1 + char_len
        else:
            current += char
            current_len += char_len
    if current:
        folded.append(current)
    return folded or [""]


def build_ics(rows: list) -> str:
    """Build minimal iCalendar string from worklog rows."""
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//WorkLogger//WorkLogger//EN", "CALSCALE:GREGORIAN",
    ]
    dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for idx, r in enumerate(rows, 1):
        if not r.has_times:
            continue
        h = calc_hours(r.start, r.end, r.break_hours)
        note = r.safe_note()
        summary_note = re.sub(r"[\r\n]+", " ", note).strip()
        summary = f"Work {h:.1f}h" + (f" — {summary_note[:60]}" if summary_note else "")
        dt_pair = shift_datetimes(r.date, r.start, r.end)
        if not dt_pair:
            continue
        start_dt, end_dt = dt_pair
        dtstart = start_dt.strftime("%Y%m%dT%H%M%S")
        dtend = end_dt.strftime("%Y%m%dT%H%M%S")
        lines += [
            "BEGIN:VEVENT",
            f"UID:worklogger-{r.date}-{dtstart}-{idx}@worklogger",
            f"DTSTAMP:{dtstamp}",
            f"DTSTART:{dtstart}", f"DTEND:{dtend}",
            f"SUMMARY:{_escape_ics_text(summary)}",
            f"DESCRIPTION:{_escape_ics_text(note[:500])}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    folded_lines: list[str] = []
    for line in lines:
        folded_lines.extend(_fold_ics_line(line))
    return "\r\n".join(folded_lines) + "\r\n"


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
                               QFont, QColor, QPen)
    from PySide6.QtCore import Qt
    from utils.i18n import _

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
    colors = pdf_colors(ctx)
    painter.fillRect(QRectF(0, 0, pw, ph), QColor(colors.page_bg))

    f = QFont("sans-serif")
    f.setPixelSize(pt(20))
    f.setBold(True)
    painter.setFont(f)
    painter.setPen(QColor(colors.text))
    th = pt(30)
    painter.drawText(QRectF(0, 0, pw, th),
                     Qt.AlignHCenter | Qt.AlignVCenter, _("Work Time Analytics"))
    f2 = QFont("sans-serif")
    f2.setPixelSize(pt(10))
    painter.setFont(f2)
    painter.setPen(QColor(colors.muted))
    y, m = ctx.year, ctx.month
    sub = (f"{tab_name}  —  {y}/{m:02d}" if tab_index == 0
           else f"{tab_name}  —  {y}")
    sh = pt(20)
    painter.drawText(QRectF(0, th, pw, sh),
                     Qt.AlignHCenter | Qt.AlignVCenter, sub)
    sep_y = th + sh + pt(4)
    painter.setPen(QPen(QColor(colors.separator), pt(1)))
    painter.drawLine(int(pw*0.03), sep_y, int(pw*0.97), sep_y)
    cursor_y = sep_y + pt(6)

    src_px = chart_widget.grab()
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

    painter.setPen(QPen(QColor(colors.separator), pt(1)))
    painter.drawLine(int(pw*0.03), cursor_y, int(pw*0.97), cursor_y)
    cursor_y += pt(10)

    detail_fn(painter, pw, ph, pt, _, cursor_y, ctx)
    painter.end()
