"""Vector dashboard printing with complete, paginated numeric tables."""

from datetime import date, timedelta
from calendar import monthrange

from PySide6.QtCore import QMarginsF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen

from worklogger.domain.analytics.scales import chart_tick_step
from worklogger.infrastructure.entry_type_labels import classification_label, work_mode_label
from worklogger.infrastructure.i18n import _

_INK = "#20323d"
_MUTED = "#536b78"
_BORDER = "#cbd8df"
_ACCENT = "#146c76"
_AVERAGE = "#b33951"
_COLORS = (_ACCENT, "#68879c", "#7472a5", "#c18837", "#4b996d", "#a96867")


def _hours(value):
    return f"{value:.2f} h"


def _range(start, end):
    return f"{start.isoformat()} - {end.isoformat()}"


def _series_label(bundle, index, label):
    if index < len(bundle.periods):
        start, end = bundle.periods[index]
        if start.day == 1 and end.month == start.month and end.day == monthrange(start.year, start.month)[1]:
            return start.strftime("%Y-%m")
        if start.day == 1 and end.month == start.month + 2:
            return _("Q{quarter}").format(quarter=(start.month - 1) // 3 + 1)
    return label


def _breakdown(dashboard, dimension):
    if dimension == "work_mode":
        return tuple((work_mode_label(key), value) for key, value in dashboard.work_modes)
    return tuple((getattr(key, "label", None) or classification_label(key), value)
                 for key, value in dashboard.entry_types)


class _DashboardPdf:
    def __init__(self, writer, painter, title, period):
        self.writer, self.painter = writer, painter
        self.title, self.period = title, period
        self.width = 1000
        self.height = round(self.width * writer.height() / writer.width())
        self.page = 1
        self.y = 0
        self._configure_page()

    def _configure_page(self):
        self.painter.setWindow(0, 0, self.width, self.height)
        self.painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.painter.fillRect(QRectF(0, 0, self.width, self.height), QColor("white"))

    def _font(self, size=12, bold=False):
        font = QFont(QGuiApplication.font())
        font.setPixelSize(size)
        font.setBold(bold)
        self.painter.setFont(font)

    def text(self, rect, text, *, size=12, bold=False, color=_INK, align=Qt.AlignmentFlag.AlignLeft):
        self._font(size, bold)
        self.painter.setPen(QColor(color))
        self.painter.drawText(rect, int(align | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap), str(text))

    def _footer(self):
        self.text(QRectF(0, self.height - 23, self.width - 40, 20), "WorkLogger", size=10, color=_MUTED)
        self.text(QRectF(self.width - 40, self.height - 23, 40, 20), str(self.page), size=10,
                  color=_MUTED, align=Qt.AlignmentFlag.AlignRight)

    def _new_page(self):
        self._footer()
        if not self.writer.newPage():
            raise RuntimeError("analytics_pdf_export_failed")
        self.page += 1
        self._configure_page()
        self.text(QRectF(0, 0, self.width, 26), self.title, size=18, bold=True)
        self.text(QRectF(0, 27, self.width, 20), self.period, size=11, color=_MUTED)
        self.y = 62

    def _card(self, rect, title):
        self.painter.setPen(QPen(QColor(_BORDER), 0.8))
        self.painter.setBrush(QColor("#f5f8fa"))
        self.painter.drawRoundedRect(rect, 5, 5)
        self.text(rect.adjusted(13, 7, -13, -rect.height() + 32), title, size=13, bold=True)

    def summary(self, dashboard, scope):
        titles = {"monthly": _("Monthly Hours"), "quarterly": _("Quarterly Hours"), "annual": _("Annual Hours")}
        stats, previous = dashboard.stats, dashboard.previous_stats
        planned = (_("Planned work unavailable") if dashboard.planned_work_days is None else
                   _("Planned work: {days:g} days").format(days=dashboard.planned_work_days))
        items = (
            (titles[scope], _hours(stats.total_hours),
             _("Goal unavailable") if dashboard.target_hours is None else
             (f"{stats.total_hours / dashboard.target_hours:.0%}  " if dashboard.target_hours > 0 else "")
             + _("of {hours:.1f}h goal").format(hours=dashboard.target_hours)),
            (_("Overtime Hours"), _hours(stats.overtime_hours),
             _("{change:+.1f}h vs previous period").format(change=stats.overtime_hours - previous.overtime_hours)),
            (_("Actual attendance"), _("{days} days").format(days=stats.work_days),
             planned + "\n" + _("{change:+d} days vs previous period").format(change=stats.work_days - previous.work_days)),
            (_("Rest Days"), _("{days} days").format(days=stats.rest_days),
             _("{change:+d} days vs previous period").format(change=stats.rest_days - previous.rest_days)),
        )
        width = (self.width - 30) / 4
        for index, (title, value, caption) in enumerate(items):
            rect = QRectF(index * (width + 10), 68, width, 106)
            self._card(rect, title)
            self.text(QRectF(rect.x() + 13, rect.y() + 31, width - 26, 34), value, size=25, bold=True)
            self.text(QRectF(rect.x() + 13, rect.y() + 67, width - 26, 32), caption, size=10, color=_MUTED)

    def chart(self, rect, title, bundle, *, line=False, average=False, caption=""):
        self._card(rect, title)
        values = bundle.line_data if line else bundle.bar_data
        if caption:
            self.text(QRectF(rect.x() + 13, rect.y() + 30, rect.width() - 26, 18), caption, size=11, color=_MUTED)
        plot = QRectF(rect.x() + 42, rect.y() + (63 if caption else 45),
                      rect.width() - 58, rect.height() - (109 if caption else 91))
        leaves = dict(bundle.leave_hours_data) if not line else {}
        if not values or not any(value > 0 or leaves.get(label, 0) > 0 for label, value in values):
            self.text(plot, _("No data"), color=_MUTED, align=Qt.AlignmentFlag.AlignCenter)
            return
        maximum = chart_tick_step(max(value + leaves.get(label, 0) for label, value in values) * 1.1) * 4
        for tick in range(5):
            y = plot.bottom() - plot.height() * tick / 4
            self.painter.setPen(QPen(QColor(_BORDER), 0.7, Qt.PenStyle.DashLine))
            self.painter.drawLine(int(plot.left()), int(y), int(plot.right()), int(y))
            self.text(QRectF(rect.x() + 3, y - 8, 34, 16), f"{maximum * tick / 4:g}h", size=9,
                      color=_MUTED, align=Qt.AlignmentFlag.AlignRight)
        step = plot.width() / len(values)
        color = _AVERAGE if average and not line else _ACCENT
        points = []
        for index, (label, value) in enumerate(values):
            x = plot.left() + step * (index + 0.5)
            y = plot.bottom() - plot.height() * value / maximum
            if not line:
                self.painter.fillRect(QRectF(x - step * 0.26, y, step * 0.52, plot.bottom() - y), QColor(color))
                leave = leaves.get(label, 0)
                height = plot.height() * leave / maximum
                if leave > 0:
                    self.painter.fillRect(QRectF(x - step * 0.26, y - height, step * 0.52, height), QColor("#c18837"))
                self.text(QRectF(x - step / 2, y - height - 17, step, 16), f"{value:.1f}", size=9,
                          align=Qt.AlignmentFlag.AlignCenter)
            label = _series_label(bundle, index, label)
            self.text(QRectF(x - step / 2, plot.bottom() + 5, step, 32), label,
                      size=8 if len(values) > 8 else 10, color=_MUTED, align=Qt.AlignmentFlag.AlignCenter)
            points.append((x, y))
        if line:
            self.painter.setPen(QPen(QColor(color), 2))
            self.painter.setBrush(QColor(color))
            for first, second in zip(points, points[1:]):
                self.painter.drawLine(int(first[0]), int(first[1]), int(second[0]), int(second[1]))
            for x, y in points:
                self.painter.drawEllipse(QRectF(x - 3, y - 3, 6, 6))
        if any(leaves.values()):
            self.text(QRectF(rect.x() + 13, rect.y() + 28, rect.width() - 26, 14),
                      _("Leave") + " (h)", size=9, color="#98620f", align=Qt.AlignmentFlag.AlignRight)

    def distribution(self, rect, dashboard, dimension):
        self._card(rect, _("Classification breakdown"))
        caption = _("Work hours by arrangement") if dimension == "work_mode" else _("Classified duration")
        self.text(QRectF(rect.x() + 13, rect.y() + 31, rect.width() - 26, 18), caption, size=10, color=_MUTED)
        values = sorted(_breakdown(dashboard, dimension), key=lambda item: (-item[1], item[0]))
        total = sum(value for _label, value in values)
        if not total:
            self.text(rect.adjusted(0, 50, 0, -20), _("No data"), color=_MUTED, align=Qt.AlignmentFlag.AlignCenter)
            return
        shown = values[:5]
        if len(values) > 5:
            shown.append((_("Other"), sum(value for _label, value in values[5:])))
        ring = QRectF(rect.x() + 20, rect.y() + 65, 110, 110)
        start = 90 * 16
        for index, (label, value) in enumerate(shown):
            color = QColor(_COLORS[index % len(_COLORS)])
            span = round(value / total * 360 * 16)
            self.painter.setPen(QPen(color, 15))
            self.painter.drawArc(ring, start, -span)
            start -= span
            y = rect.y() + 60 + index * 21
            self.painter.fillRect(QRectF(rect.x() + 151, y + 7, 7, 7), color)
            self._font(11)
            available = int(rect.width() - 285)
            short = self.painter.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, available)
            self.text(QRectF(rect.x() + 165, y, available, 20), short, size=11)
            self.text(QRectF(rect.right() - 115, y, 102, 20), f"{value:.2f}h ({value / total:.0%})", size=10,
                      color=_MUTED, align=Qt.AlignmentFlag.AlignRight)
        self.text(ring.adjusted(15, 25, -15, -25), _hours(total), size=13, bold=True,
                  align=Qt.AlignmentFlag.AlignCenter)

    def table(self, title, headers, rows, widths):
        header_height = 32
        if self.y + 100 > self.height - 35:
            self._new_page()
        self.text(QRectF(0, self.y, self.width, 24), title, size=15, bold=True)
        self.y += 26
        def headings():
            x = 0
            for text, fraction in zip(headers, widths):
                width = self.width * fraction
                self.painter.fillRect(QRectF(x, self.y, width, header_height), QColor("#e3eef1"))
                self.text(QRectF(x + 7, self.y + 2, width - 14, header_height - 4), text, size=11, bold=True)
                x += width
            self.y += header_height
        headings()
        for row in rows:
            self._font(11)
            metrics = self.painter.fontMetrics()
            flags = []
            for value, width in zip(row, widths):
                longest = max(str(value).split(), key=len, default="")
                wrap = Qt.TextFlag.TextWrapAnywhere if metrics.horizontalAdvance(longest) > self.width * width - 14 else Qt.TextFlag.TextWordWrap
                flags.append(int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | wrap))
            height = max(22, *(metrics.boundingRect(QRectF(0, 0, self.width * width - 14, 1000).toRect(), flag, str(value)).height() + 6
                              for value, width, flag in zip(row, widths, flags)))
            if self.y + height > self.height - 35:
                self._new_page()
                self.text(QRectF(0, self.y, self.width, 24), title, size=15, bold=True)
                self.y += 26
                headings()
            x = 0
            for value, width, flag in zip(row, widths, flags):
                self._font(11)
                self.painter.setPen(QColor(_INK))
                self.painter.drawText(QRectF(x + 7, self.y + 3, self.width * width - 14, height - 6), flag, str(value))
                x += self.width * width
            self.painter.setPen(QPen(QColor(_BORDER), 0.6))
            self.painter.drawLine(0, int(self.y + height), self.width, int(self.y + height))
            self.y += height
        self.y += 12

    def details(self, dashboard):
        self._new_page()
        stats, previous = dashboard.stats, dashboard.previous_stats
        previous_end = dashboard.period_start - timedelta(days=1) if dashboard.period_start > date.min else date.min
        previous_start = previous_end - timedelta(days=dashboard.previous_total_days - 1) if dashboard.previous_total_days else None
        self.text(QRectF(0, self.y, self.width, 34), _("Previous period") + ": " +
                  (_range(previous_start, previous_end) if previous_start else _("No data")), size=11, color=_MUTED)
        self.y += 40
        summary = tuple((label, _hours(getattr(stats, key)), _hours(getattr(previous, key)),
                         f"{getattr(stats, key) - getattr(previous, key):+.2f} h")
                        for label, key in ((_('Work hours'), "total_hours"), (_('Overtime Hours'), "overtime_hours"),
                                           (_('Daily Average'), "average_hours")))
        summary += tuple((label, _("{days} days").format(days=getattr(stats, key)),
                          _("{days} days").format(days=getattr(previous, key)),
                          f"{getattr(stats, key) - getattr(previous, key):+d}")
                         for label, key in ((_('Actual attendance'), "work_days"), (_('Rest Days'), "rest_days"),
                                            (_('Leave days'), "leave_days")))
        summary += ((_("Planned work"), _("Planned work unavailable") if dashboard.planned_work_days is None else
                     _("{days} days").format(days=f"{dashboard.planned_work_days:g}"), "-", "-"),
                    (_("Goal"), _("Goal unavailable") if dashboard.target_hours is None else _hours(dashboard.target_hours), "-", "-"),
                    (_("Goal calculation"), _("From work schedule") if dashboard.target_mode == "schedule" else _("Custom target"), "-", "-"),
                    (_("Calendar days"), str(dashboard.total_days), str(dashboard.previous_total_days), "-"))
        self.table(_("Summary"), (_("Metric"), _("Selected period"), _("Previous period"), _("Change")), summary, (.34, .22, .22, .22))
        self.text(QRectF(0, self.y, self.width, 32), _("Attendance counts dates with positive worked hours, including scheduled days off. Planned work follows the weekly schedule and enabled regional public holidays. This is not an attendance rate."), size=10, color=_MUTED)
        self.y += 38
        averages = dict(dashboard.average.bar_data)
        leave = dict(dashboard.trend.leave_hours_data)
        average_leave = dict(dashboard.average.leave_hours_data)
        rows = []
        for index, (label, value) in enumerate(dashboard.trend.bar_data):
            period = _range(*dashboard.trend.periods[index]) if index < len(dashboard.trend.periods) else label.replace("\n", " ")
            rows.append((period, _hours(value), _hours(averages.get(label, 0)), _hours(leave.get(label, 0)), _hours(average_leave.get(label, 0))))
        self.table(_("Work Hours Trend") + " / " + _("Average Work Hours"),
                   (_("Period"), _("Worked hours"), _("Average Work Hours"), _("Leave hours"), _("Average leave hours")),
                   rows, (.32, .17, .17, .17, .17))
        for dimension, title in (("entry_type", _("Classification")), ("work_mode", _("Work arrangement"))):
            values = _breakdown(dashboard, dimension)
            total = sum(value for _label, value in values)
            self.table(title, (title, _("Hours"), _("Share")),
                       tuple((label, _hours(value), f"{value / total:.2%}" if total else "0.00%") for label, value in values)
                       or ((_("No data"), _hours(0), "0.00%"),), (.64, .18, .18))
        bundle = dashboard.daily_average_trend
        self.table(_("Daily Average"), (_("Period"), _("Average Work Hours")),
                   tuple((_range(*bundle.periods[index]) if index < len(bundle.periods) else label, _hours(value))
                         for index, (label, value) in enumerate(bundle.line_data)), (.65, .35))
        self._footer()


def write_dashboard_pdf(destination, dashboard, *, scope, breakdown_dimension, generated_at):
    if QGuiApplication.instance() is None:
        raise RuntimeError("pdf_application_required")
    title = _("Analytics") + " - " + {"monthly": _("Monthly"), "quarterly": _("Quarterly"), "annual": _("Annual")}[scope]
    period = _range(dashboard.period_start, dashboard.period_end)
    writer = QPdfWriter(str(destination))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageOrientation(QPageLayout.Orientation.Landscape)
    writer.setPageMargins(QMarginsF(12, 12, 12, 12))
    writer.setResolution(144)
    writer.setTitle(title + " " + period)
    writer.setCreator("WorkLogger")
    painter = QPainter(writer)
    if not painter.isActive():
        raise RuntimeError("analytics_pdf_export_failed")
    try:
        page = _DashboardPdf(writer, painter, title, period)
        page.text(QRectF(0, 0, 650, 28), title, size=22, bold=True)
        page.text(QRectF(0, 32, 650, 22), period, size=12, color=_MUTED)
        page.text(QRectF(650, 7, 350, 42), _("Generated at: {time}").format(time=generated_at.isoformat(timespec="seconds")),
                  size=10, color=_MUTED, align=Qt.AlignmentFlag.AlignRight)
        page.summary(dashboard, scope)
        width, height = 492, (page.height - 270) / 2
        page.chart(QRectF(0, 190, width, height), _("Work Hours Trend"), dashboard.trend)
        page.chart(QRectF(508, 190, width, height), _("Average Work Hours"), dashboard.average, average=True)
        bottom = 200 + height
        page.distribution(QRectF(0, bottom, width, height), dashboard, breakdown_dimension)
        page.chart(QRectF(508, bottom, width, height), _("Daily Average"), dashboard.daily_average_trend, line=True,
                   caption=_hours(dashboard.stats.average_hours) + "   " + _("{change:+.1f}h vs previous period").format(
                       change=dashboard.stats.average_hours - dashboard.previous_stats.average_hours))
        page.text(QRectF(0, page.height - 51, page.width, 16), _("Full values are listed in the following tables."), size=10, color=_MUTED)
        page.details(dashboard)
    finally:
        painter.end()
    del page, painter, writer
    with destination.open("rb") as handle:
        if handle.read(5) != b"%PDF-":
            raise RuntimeError("analytics_pdf_export_failed")
        handle.seek(max(0, destination.stat().st_size - 4096))
        if b"%%EOF" not in handle.read(4096):
            raise RuntimeError("analytics_pdf_export_failed")
