"""Theme-aware analytics charts with responsive plot bounds."""

from __future__ import annotations

from math import floor, log10

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPalette
from PySide6.QtWidgets import QSizePolicy, QWidget

from worklogger.domain.analytics.models import ChartDataBundle
from worklogger.infrastructure.i18n import _
from worklogger.presentation.theme import ThemeEngine
from worklogger.presentation.date_labels import duration_label


def chart_tick_step(maximum: float) -> float:
    raw = max(1.0, maximum) / 4
    magnitude = 10 ** floor(log10(raw))
    return next(step * magnitude for step in (1, 2, 2.5, 5, 10) if step * magnitude >= raw)


def chart_palette(widget: QWidget):
    palette = widget.palette()
    return ThemeEngine().palette(
        "custom", dark=palette.color(QPalette.ColorRole.Window).lightness() < 128,
        custom_color=palette.color(QPalette.ColorRole.Highlight).name(),
    )


class ComboChart(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bundle = ChartDataBundle((), (), frozenset(), (), ())
        self._mode = "bar"
        self._average = False
        self.setObjectName("combo_chart_widget")
        self.setMinimumSize(180, 120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, bundle: ChartDataBundle, *, mode: str = "bar", average: bool = False) -> None:
        self._bundle = bundle
        self._mode = mode if mode in {"bar", "line"} else "bar"
        self._average = average
        self.update()

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = painter.font()
        font.setPixelSize(10)
        painter.setFont(font)
        colors = chart_palette(self)
        rect = QRectF(34, 25, max(1, self.width() - 44), max(1, self.height() - 48))
        values = self._bundle.line_data if self._mode == "line" else self._bundle.bar_data
        leave_values = dict(self._bundle.leave_hours_data)
        if not values or not any(value > 0 or leave_values.get(label, 0) > 0 for label, value in values):
            painter.setPen(QColor(colors.muted_text))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, _("No data"))
            return
        maximum = max((float(value) + leave_values.get(label, 0.0) for label, value in values), default=1.0)
        maximum = chart_tick_step(maximum * 1.1) * 4
        for tick in range(5):
            y = rect.bottom() - rect.height() * tick / 4
            painter.setPen(QPen(QColor(colors.border), 1, Qt.PenStyle.DashLine))
            painter.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))
            painter.setPen(QColor(colors.muted_text))
            painter.drawText(QRectF(0, y - 8, 30, 16), Qt.AlignmentFlag.AlignRight, f"{maximum * tick / 4:g}{_('h')}")
        color = QColor(colors.danger if self._average and self._mode == "bar" else colors.accent)
        painter.setPen(color)
        legend = _("Average") if self._average else _("Work hours")
        if any(value > 0 for value in leave_values.values()):
            legend += " / " + _("Leave")
        painter.drawText(QRectF(34, 0, self.width() - 44, 18), Qt.AlignmentFlag.AlignRight, legend)
        step = rect.width() / len(values)
        points: list[tuple[float, float]] = []
        for index, (label, value) in enumerate(values):
            x = rect.left() + step * (index + 0.5)
            height = rect.height() * float(value) / maximum
            top = rect.bottom() - height
            if self._mode == "bar":
                painter.fillRect(QRectF(x - step * 0.27, top, step * 0.54, height), color)
                leave = leave_values.get(label, 0.0)
                if leave > 0:
                    leave_height = rect.height() * leave / maximum
                    painter.fillRect(QRectF(x - step * 0.27, top - leave_height, step * 0.54, leave_height), QBrush(QColor(colors.accent), Qt.BrushStyle.Dense4Pattern))
                    if leave_height >= 16:
                        painter.setPen(QColor(colors.text))
                        painter.drawText(QRectF(x - step / 2, top - leave_height / 2 - 8, step, 16), Qt.AlignmentFlag.AlignCenter, f"{leave:.1f}")
                if step >= 28:
                    inside = height >= 24
                    painter.setPen(QColor("#ffffff" if inside else colors.text))
                    painter.drawText(QRectF(x - step / 2, top + 3 if inside else top - 18, step, 16), Qt.AlignmentFlag.AlignCenter, f"{value:.1f}")
            points.append((x, top))
            painter.setPen(QColor(colors.muted_text))
            painter.drawText(QRectF(x - step / 2, rect.bottom() + 5, step, 16), Qt.AlignmentFlag.AlignCenter, painter.fontMetrics().elidedText(str(label), Qt.TextElideMode.ElideRight, int(step)))
        if self._mode == "line":
            area = QPainterPath()
            area.moveTo(points[0][0], rect.bottom())
            for x, y in points:
                area.lineTo(x, y)
            area.lineTo(points[-1][0], rect.bottom())
            area.closeSubpath()
            fill = QColor(color)
            fill.setAlpha(24)
            painter.fillPath(area, fill)
            painter.setPen(QPen(color, 2))
            for first, second in zip(points, points[1:]):
                painter.drawLine(int(first[0]), int(first[1]), int(second[0]), int(second[1]))
            painter.setBrush(color)
            for x, y in points:
                painter.drawEllipse(QRectF(x - 3, y - 3, 6, 6))


class DonutChart(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("work_mode_chart_widget")
        self._segments: tuple[tuple[str, float], ...] = ()
        self._keys: tuple[str, ...] = ()
        self.setMinimumSize(180, 144)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_segments(self, segments: tuple[tuple[str, float], ...], *, keys: tuple[str, ...] = ()) -> None:
        self._segments = tuple((label, value) for label, value in segments if value > 0)
        self._keys = tuple(keys[index] if index < len(keys) else "" for index, (_label, value) in enumerate(segments) if value > 0)
        self.setToolTip("\n".join(f"{label}: {duration_label(value)}" for label, value in self._segments))
        self.update()

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = chart_palette(self)
        total = sum(value for _, value in self._segments)
        painter.setPen(QColor(colors.muted_text))
        if total <= 0:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, _("No data"))
            return
        diameter = min(self.height() - 20, self.width() * 0.36, 140)
        ring = QRectF(12, (self.height() - diameter) / 2, diameter, diameter)
        segment_colors = (colors.accent, colors.success, colors.warning, colors.danger, colors.muted_text)
        start = 90 * 16
        font = painter.font()
        font.setPixelSize(11)
        painter.setFont(font)
        x = ring.right() + 15
        available = max(0, self.width() - x - 16)
        details = tuple(_("{duration} ({percent:.0f}%)").format(duration=duration_label(value), percent=value / total * 100) for _label, value in self._segments)
        inline = all(painter.fontMetrics().horizontalAdvance(label + "  " + detail) <= available for (label, _value), detail in zip(self._segments, details))
        row_height = 28 if inline else 34
        for index, (label, value) in enumerate(self._segments):
            keyed_colors = {
                "normal": colors.accent, "remote": QColor(colors.accent).lighter(145).name(),
                "business_trip": ThemeEngine().palette("purple", dark=colors.dark).accent,
                "leave": colors.danger,
            }
            color = QColor(keyed_colors.get(self._keys[index], segment_colors[index % len(segment_colors)]))
            span = round(360 * 16 * value / total)
            painter.setPen(QPen(color, 15))
            painter.drawArc(ring.adjusted(9, 9, -9, -9), start, -span)
            start -= span
            y = (self.height() - len(self._segments) * row_height) / 2 + index * row_height
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(QRectF(x, y + 5, 6, 6))
            painter.setPen(QColor(colors.text))
            detail = details[index]
            label_width = available - painter.fontMetrics().horizontalAdvance(detail) - 8 if inline else available
            painter.drawText(QRectF(x + 12, y, label_width, 18), Qt.AlignmentFlag.AlignLeft, painter.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, int(label_width)))
            painter.setPen(QColor(colors.muted_text))
            painter.drawText(QRectF(x + 12, y if inline else y + 16, available, 18), Qt.AlignmentFlag.AlignRight if inline else Qt.AlignmentFlag.AlignLeft, painter.fontMetrics().elidedText(detail, Qt.TextElideMode.ElideRight, int(available)))
        painter.setPen(QColor(colors.text))
        center = ring.adjusted(18, 18, -18, -18)
        total_text = duration_label(total)
        while painter.fontMetrics().horizontalAdvance(total_text) > center.width() - 4 and font.pixelSize() > 1:
            font.setPixelSize(font.pixelSize() - 1)
            painter.setFont(font)
        painter.drawText(center, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextSingleLine, total_text)
