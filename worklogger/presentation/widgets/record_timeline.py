"""Proportional time lanes for explicit record replacement previews."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from html import escape

from PySide6.QtCore import QEvent, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from worklogger.domain.worklog.models import WorkLog
from worklogger.domain.worklog.rules import entry_interval, shift_datetimes
from worklogger.infrastructure.i18n import _
from worklogger.presentation.theme import ThemeEngine
from worklogger.presentation.theme.context import current_colors
from worklogger.presentation.theme.theme_engine import contrasting_text_color
from worklogger.presentation.entry_type_labels import entry_type_label


@dataclass(frozen=True)
class _Period:
    record: WorkLog
    start: datetime
    end: datetime


class RecordReplacementTimeline(QWidget):
    def __init__(self, plan, parent=None):
        super().__init__(parent)
        self.setObjectName("record_replacement_timeline")
        self.setAccessibleName(_("Time replacement preview"))
        self._keep_outside = True
        records = (*plan.affected, plan.incoming)
        captured = all(item.started_at is not None for item in records)
        self._zone = records[0].started_at.tzinfo if captured else None
        def period(record):
            if captured:
                start, end = entry_interval(record)
            elif record.has_times:
                start, end = shift_datetimes(record.day, record.start_time, record.end_time)
            else:
                start = datetime.combine(record.day, time())
                end = start + timedelta(days=1)
            return _Period(record, start, end)
        self._existing = tuple(period(item) for item in plan.affected)
        self._incoming = period(plan.incoming)
        self._start = min(item.start for item in (*self._existing, self._incoming))
        self._end = max(item.end for item in (*self._existing, self._incoming))
        self.setMinimumWidth(360)
        self.setMinimumHeight(self.sizeHint().height())
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._describe()

    def sizeHint(self):
        return QSize(600, self.fontMetrics().height() * 4 + 44)

    def set_keep_outside(self, keep):
        self._keep_outside = bool(keep)
        self._describe()
        self.update()

    def _describe(self):
        mode = _("Replace overlapping time only") if self._keep_outside else _("Replace entire overlapping records")
        self.setAccessibleDescription("\n".join((mode, self._description(self._incoming),
                                                 *(self._description(item) for item in self._existing))))

    def _local(self, moment):
        return moment.astimezone(self._zone) if self._zone is not None else moment

    def _description(self, period):
        return f"{entry_type_label(period.record.entry_type)}: {self._local(period.start).isoformat(' ')} - {self._local(period.end).isoformat(' ')}"

    def _time_label(self, moment):
        first, last, value = (self._local(item) for item in (self._start, self._end, moment))
        pattern = "%H:%M"
        if first.date() != last.date():
            pattern = "%Y-%m-%d %H:%M" if first.year != last.year else "%m-%d %H:%M"
        if any(item.second for item in (self._start, self._end, self._incoming.start, self._incoming.end)):
            pattern += ":%S"
        if first.utcoffset() != last.utcoffset():
            pattern += " %z"
        return value.strftime(pattern)

    def _lane(self, incoming):
        metrics = self.fontMetrics()
        label_width = max(metrics.horizontalAdvance(_("New period")), metrics.horizontalAdvance(_("Existing records")))
        top = metrics.height() + 8
        height = max(20, metrics.height() + 4)
        return QRectF(label_width + 16, top if incoming else top + height + 8,
                      max(1, self.width() - label_width - 20), height)

    def period_rect(self, period, *, incoming=False):
        lane = self._lane(incoming)
        span = (self._end - self._start).total_seconds()
        left = (period.start - self._start).total_seconds() / span
        right = (period.end - self._start).total_seconds() / span
        return QRectF(lane.left() + lane.width() * left, lane.top(), max(1, lane.width() * (right - left)), lane.height())

    def _color(self, record):
        colors = current_colors()
        return QColor(ThemeEngine().entry_type_marker_color(record.entry_type, dark=colors.dark)
                      or (colors.muted_text if record.is_break else colors.accent))

    def _draw_period(self, painter, period, *, incoming=False):
        rect = self.period_rect(period, incoming=incoming)
        color = self._color(period.record)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(rect, 3, 3)
        caption = entry_type_label(period.record.entry_type)
        if self.fontMetrics().horizontalAdvance(caption) + 12 < rect.width():
            painter.setPen(contrasting_text_color(color))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, caption)

    def paintEvent(self, _event):
        colors, metrics = current_colors(), self.fontMetrics()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        try:
            for incoming, label in ((True, _("New period")), (False, _("Existing records"))):
                lane = self._lane(incoming)
                painter.setPen(QColor(colors.muted_text))
                painter.drawText(QRectF(0, lane.top(), lane.left() - 12, lane.height()),
                                 Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
            old_lane, new_lane = self._lane(False), self._lane(True)
            painter.setPen(QPen(QColor(colors.border), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(old_lane, 3, 3)
            painter.save()
            if not self._keep_outside:
                painter.setOpacity(0.25)
            for period in self._existing:
                self._draw_period(painter, period)
            painter.restore()
            new_rect = self.period_rect(self._incoming, incoming=True)
            painter.setPen(QPen(QColor(colors.accent), 1, Qt.PenStyle.DotLine))
            for x in (new_rect.left(), new_rect.right()):
                painter.drawLine(int(x), int(new_rect.bottom() + 2), int(x), int(old_lane.bottom() + 2))
            self._draw_period(painter, self._incoming, incoming=True)
            painter.setPen(QColor(colors.text))
            caption = f"{self._time_label(self._incoming.start)} - {self._time_label(self._incoming.end)}"
            label_width = min(new_lane.width(), metrics.horizontalAdvance(caption) + 4)
            label_left = max(new_lane.left(), min(new_rect.center().x() - label_width / 2, new_lane.right() - label_width))
            painter.drawText(QRectF(label_left, 0, label_width, metrics.height() + 4),
                             Qt.AlignmentFlag.AlignCenter, caption)
            axis = QRectF(old_lane.left(), old_lane.bottom() + 6, old_lane.width(), metrics.height() + 4)
            painter.setPen(QColor(colors.muted_text))
            painter.drawText(axis, Qt.AlignmentFlag.AlignLeft, self._time_label(self._start))
            painter.drawText(axis, Qt.AlignmentFlag.AlignRight, self._time_label(self._end))
        finally:
            painter.end()

    def event(self, event):
        if event.type() == QEvent.Type.ToolTip:
            for period, incoming in ((self._incoming, True), *((item, False) for item in self._existing)):
                if self.period_rect(period, incoming=incoming).contains(event.pos()):
                    QToolTip.showText(event.globalPos(), "<qt>" + escape(self._description(period)) + "</qt>", self)
                    return True
            QToolTip.hideText()
            return True
        if event.type() == QEvent.Type.FontChange:
            self.setMinimumHeight(self.sizeHint().height())
            self.updateGeometry()
        return super().event(event)
