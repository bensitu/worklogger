"""Export and import services: CSV, ICS, PDF.

Calendar parsing is delegated to ``calendar_service.parse_ics_rich`` so
event time information is preserved consistently across imports.

``render_pdf`` accepts a ``PdfContext`` data object to keep this service
layer independent from UI widget classes.
"""

from __future__ import annotations
import csv
import re
from dataclasses import dataclass, field
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


@dataclass(frozen=True)
class PdfMetric:
    label: str
    value: str


@dataclass(frozen=True)
class PdfDetailSection:
    summary: list[PdfMetric] = field(default_factory=list)
    headers: list[tuple[str, float]] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    disabled_rows: set[int] = field(default_factory=set)


def pdf_colors(ctx: "PdfContext") -> PdfColors:
    """Return print-safe PDF colors.

    PDF exports intentionally keep a light page even when the app is in dark
    mode. That keeps exported text readable in PDF viewers and on paper.
    """
    from config.themes import theme_colors

    accent, _hover, accent_dim, stat_bg, stat_border = theme_colors(
        ctx.theme,
        False,
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
    # Accept both plain UTF-8 and UTF-8 with BOM, and stream rows to avoid
    # loading large imports entirely into memory.
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        first_row = next(reader, None)
        if not first_row:
            raise ValueError("empty")
        raw_header = [h.strip().lower() for h in first_row]
        header = set(raw_header)
        normalized = {"break" if h == "lunch" else h for h in header}
        missing = required_cols - normalized
        if missing:
            raise ValueError(f"missing:{','.join(missing)}")
        idx_map = {name: i for i, name in enumerate(raw_header)}
        break_idx = idx_map.get("break", idx_map.get("lunch"))
        for i, row in enumerate(reader, 2):
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
        if not r.has_times or r.is_leave:
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
    chart_pixmap,
    detail: PdfDetailSection,
    ctx: "PdfContext",
    ai_narrative: str | None = None,
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
    from PySide6.QtGui import (
        QBrush,
        QColor,
        QFont,
        QFontMetrics,
        QPageLayout,
        QPageSize,
        QPainter,
        QPen,
    )
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

    def fill_page() -> None:
        painter.fillRect(QRectF(0, 0, pw, ph), QColor(colors.page_bg))

    def new_page() -> None:
        printer.newPage()
        fill_page()

    def ensure_space(cursor: int, required: int, *, top_margin: int = 0) -> int:
        if cursor + required <= ph - pt(18):
            return cursor
        new_page()
        return top_margin or pt(18)

    fill_page()

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

    src_px = chart_pixmap
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

    narrative = str(ai_narrative or "").strip()
    if narrative:
        cursor_y = _draw_ai_narrative(
            painter,
            narrative,
            cursor_y,
            pw,
            ph,
            pt,
            colors,
            ensure_space,
            new_page,
            _("AI Summary"),
        )

    cursor_y = ensure_space(cursor_y, pt(14))
    painter.setPen(QPen(QColor(colors.separator), pt(1)))
    painter.drawLine(int(pw*0.03), cursor_y, int(pw*0.97), cursor_y)
    cursor_y += pt(10)

    _draw_detail_section(
        painter,
        detail,
        cursor_y,
        pw,
        ph,
        pt,
        colors,
        ensure_space,
        new_page,
    )
    painter.end()


def _wrap_text(text: str, metrics, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in str(text or "").splitlines():
        if not paragraph.strip():
            lines.append("")
            continue
        words = paragraph.split(" ")
        current = ""
        for word in words:
            candidate = word if not current else f"{current} {word}"
            if metrics.horizontalAdvance(candidate) <= max_width:
                current = candidate
                continue
            if current:
                lines.append(current)
                current = ""
            if metrics.horizontalAdvance(word) <= max_width:
                current = word
                continue
            chunk = ""
            for char in word:
                candidate = chunk + char
                if metrics.horizontalAdvance(candidate) <= max_width:
                    chunk = candidate
                else:
                    if chunk:
                        lines.append(chunk)
                    chunk = char
            current = chunk
        if current:
            lines.append(current)
    return lines


def _draw_ai_narrative(
    painter,
    narrative: str,
    cursor_y: int,
    pw: int,
    ph: int,
    pt,
    colors: PdfColors,
    ensure_space,
    new_page,
    title: str,
) -> int:
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QFontMetrics, QPen, QBrush

    x = int(pw * 0.05)
    w = int(pw * 0.90)
    body_font = QFont("sans-serif")
    body_font.setPixelSize(pt(9))
    metrics = QFontMetrics(body_font)
    line_h = max(metrics.height() + pt(2), pt(12))
    lines = _wrap_text(narrative, metrics, w - pt(20))
    idx = 0
    first_block = True
    while idx < len(lines):
        title_h = pt(18) if first_block else pt(0)
        cursor_y = ensure_space(cursor_y, title_h + line_h + pt(18))
        available = max(line_h, ph - cursor_y - pt(24) - title_h)
        capacity = max(1, available // line_h)
        block_lines = lines[idx:idx + capacity]
        box_h = title_h + len(block_lines) * line_h + pt(18)
        painter.setPen(QPen(QColor(colors.separator), pt(1)))
        painter.setBrush(QBrush(QColor(colors.panel_bg)))
        painter.drawRoundedRect(QRectF(x, cursor_y, w, box_h), pt(5), pt(5))
        top = cursor_y + pt(8)
        if first_block:
            title_font = QFont("sans-serif")
            title_font.setPixelSize(pt(10))
            title_font.setBold(True)
            painter.setFont(title_font)
            painter.setPen(QColor(colors.text))
            painter.drawText(
                QRectF(x + pt(10), top, w - pt(20), pt(14)),
                Qt.AlignLeft | Qt.AlignVCenter,
                title,
            )
            top += title_h
        painter.setFont(body_font)
        painter.setPen(QColor(colors.text))
        for line in block_lines:
            painter.drawText(
                QRectF(x + pt(10), top, w - pt(20), line_h),
                Qt.AlignLeft | Qt.AlignVCenter,
                line,
            )
            top += line_h
        cursor_y += box_h + pt(10)
        idx += len(block_lines)
        first_block = False
        if idx < len(lines):
            new_page()
            cursor_y = pt(18)
    return cursor_y


def _draw_detail_section(
    painter,
    detail: PdfDetailSection,
    cursor_y: int,
    pw: int,
    ph: int,
    pt,
    colors: PdfColors,
    ensure_space,
    new_page,
) -> int:
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QFontMetrics, QPen, QBrush

    if detail.summary:
        cursor_y = ensure_space(cursor_y, pt(40))
        box_h = pt(34)
        cw = pw / max(1, len(detail.summary))
        painter.setBrush(QBrush(QColor(colors.panel_bg)))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(QRectF(0, cursor_y, pw, box_h), pt(6), pt(6))
        for i, metric in enumerate(detail.summary):
            cx = i * cw
            label_font = QFont("sans-serif")
            label_font.setPixelSize(pt(8))
            painter.setFont(label_font)
            painter.setPen(QColor(colors.muted))
            painter.drawText(
                QRectF(cx, cursor_y + pt(4), cw, pt(12)),
                Qt.AlignCenter,
                metric.label,
            )
            value_font = QFont("sans-serif")
            value_font.setPixelSize(pt(11))
            value_font.setBold(True)
            painter.setFont(value_font)
            painter.setPen(QColor(colors.text))
            painter.drawText(
                QRectF(cx, cursor_y + pt(16), cw, pt(14)),
                Qt.AlignCenter,
                metric.value,
            )
        cursor_y += box_h + pt(6)

    if not detail.headers:
        return cursor_y

    header_h = pt(16)
    row_h = pt(15)
    header_font = QFont("sans-serif")
    header_font.setPixelSize(pt(8))
    header_font.setBold(True)
    row_font = QFont("sans-serif")
    row_font.setPixelSize(pt(8))
    row_metrics = QFontMetrics(row_font)

    def draw_header(y_pos: int) -> int:
        painter.setBrush(QBrush(QColor(colors.panel_header_bg)))
        painter.setPen(Qt.NoPen)
        painter.drawRect(QRectF(0, y_pos, pw, header_h))
        painter.setFont(header_font)
        painter.setPen(QColor(colors.text))
        x = 0
        for label, frac in detail.headers:
            cw = pw * frac
            painter.drawText(
                QRectF(x + pt(2), y_pos, cw - pt(4), header_h),
                Qt.AlignVCenter | Qt.AlignLeft,
                label,
            )
            x += cw
        return y_pos + header_h

    cursor_y = ensure_space(cursor_y, header_h + row_h)
    cursor_y = draw_header(cursor_y)
    for row_idx, row in enumerate(detail.rows):
        if cursor_y + row_h > ph - pt(18):
            new_page()
            cursor_y = draw_header(pt(18))
        bg = QColor(colors.row_alt_bg if row_idx % 2 == 0 else colors.row_bg)
        painter.setBrush(QBrush(bg))
        painter.setPen(Qt.NoPen)
        painter.drawRect(QRectF(0, cursor_y, pw, row_h))
        painter.setFont(row_font)
        painter.setPen(
            QColor(colors.disabled if row_idx in detail.disabled_rows else colors.text)
        )
        x = 0
        for value, (_label, frac) in zip(row, detail.headers):
            cw = pw * frac
            text = row_metrics.elidedText(str(value), Qt.ElideRight, int(cw - pt(6)))
            painter.drawText(
                QRectF(x + pt(3), cursor_y, cw - pt(6), row_h),
                Qt.AlignVCenter | Qt.AlignLeft,
                text,
            )
            x += cw
        cursor_y += row_h
    return cursor_y
