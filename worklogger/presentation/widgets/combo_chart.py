"""Theme-aware analytics charts with responsive plot bounds."""

from __future__ import annotations

from worklogger.presentation.theme.theme_engine import ThemeEngine, contrasting_text_color

from math import ceil, isfinite
from worklogger.domain.analytics.scales import chart_tick_step as chart_tick_step

from PySide6.QtCore import QEvent, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from worklogger.domain.analytics.models import ChartDataBundle
from worklogger.infrastructure.i18n import _
from worklogger.presentation.theme.context import current_colors
from worklogger.presentation.date_labels import duration_label


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
        if any(not isfinite(value) for series in (bundle.bar_data, bundle.line_data, bundle.leave_hours_data)
               for _label, value in series):
            bundle = ChartDataBundle((), (), frozenset(), (), ())
        self._bundle = bundle
        self._mode = mode if mode in {"bar", "line"} else "bar"
        self._average = average
        values = bundle.line_data if self._mode == "line" else bundle.bar_data
        leave = dict(bundle.leave_hours_data)
        details = []
        for label, value in values:
            description = f"{label.replace(chr(10), ' ')}: {duration_label(value)}"
            if leave.get(label, 0) > 0:
                description += f"; {_('Leave')}: {duration_label(leave[label])}"
            details.append(description)
        self.setAccessibleName(_("Average") if average else _("Work hours"))
        self.setAccessibleDescription("\n".join(details) or _("No data"))
        self.setToolTip(self.accessibleDescription())
        self.update()

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = painter.font()
        font.setPixelSize(10)
        painter.setFont(font)
        colors = current_colors()
        values = self._bundle.line_data if self._mode == "line" else self._bundle.bar_data
        multiline = any("\n" in label for label, _value in values)
        rect = QRectF(34, 25, max(1, self.width() - 44), max(1, self.height() - (62 if multiline else 48)))
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
                    painter.setPen(contrasting_text_color(color) if inside else QColor(colors.text))
                    painter.drawText(QRectF(x - step / 2, top + 3 if inside else top - 18, step, 16), Qt.AlignmentFlag.AlignCenter, f"{value:.1f}")
            points.append((x, top))
            painter.setPen(QColor(colors.muted_text))
            for row, text in enumerate(str(label).splitlines()):
                painter.drawText(QRectF(x - step / 2, rect.bottom() + 5 + row * 14, step, 16), Qt.AlignmentFlag.AlignCenter, painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(step)))
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
        self.setObjectName("distribution_chart_widget")
        self._segments: tuple[tuple[str, float], ...] = ()
        self._keys: tuple[str, ...] = ()
        self._categories: tuple[str, ...] = ()
        self.setMinimumSize(180, 144)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_segments(self, segments: tuple[tuple[str, float], ...], *, keys: tuple[str, ...] = (), categories: tuple[str, ...] = (),
                     caption: str = "") -> None:
        self._segments = tuple((label, value) for label, value in segments if value > 0)
        self._keys = tuple(keys[index] if index < len(keys) else "" for index, (_label, value) in enumerate(segments) if value > 0)
        self._categories = tuple(categories[index] if index < len(categories) else "work" for index, (_label, value) in enumerate(segments) if value > 0)
        self.setToolTip("\n".join(f"{label}: {duration_label(value)}" for label, value in self._segments))
        self.setAccessibleName(caption or _("Classification"))
        self.setAccessibleDescription(self.toolTip() or _("No data"))
        self._fit_legend()
        self.update()

    def _legend_layout(self):
        font = QFont(self.font())
        font.setPixelSize(11)
        metrics = QFontMetrics(font)
        total = sum(value for _, value in self._segments)
        details = tuple(_("{duration} ({percent:.0f}%)").format(duration=duration_label(value), percent=value / total * 100)
                        for _label, value in self._segments) if total else ()
        legend_offset, right_margin = 27, 16
        required_width = max((metrics.horizontalAdvance(label) + metrics.horizontalAdvance(detail) + 8
                              for (label, _value), detail in zip(self._segments, details)), default=0)
        diameter = min(self.width() * 0.36, 140,
                       max(96, self.width() - legend_offset - right_margin - required_width))
        x = diameter + legend_offset
        available = max(0, self.width() - x - right_margin)
        inline = required_width <= available
        row_height = max(20, metrics.height() + 4) if inline else max(34, 2 * metrics.height() + 6)
        return font, diameter, x, available, details, inline, row_height

    def _fit_legend(self):
        _font, diameter, _x, _available, _details, _inline, row_height = self._legend_layout()
        self.setMinimumHeight(ceil(max(144, diameter + 16, len(self._segments) * row_height + 16)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_legend()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange) and hasattr(self, "_segments"):
            self._fit_legend()

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = current_colors()
        total = sum(value for _, value in self._segments)
        painter.setPen(QColor(colors.muted_text))
        if total <= 0:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, _("No data"))
            return
        font, diameter, x, available, details, inline, row_height = self._legend_layout()
        ring = QRectF(12, (self.height() - diameter) / 2, diameter, diameter)
        segment_colors = (colors.accent, colors.success, colors.warning, colors.danger, colors.muted_text)
        start = 90 * 16
        painter.setFont(font)
        engine = ThemeEngine()
        for index, (label, value) in enumerate(self._segments):
            key = self._keys[index]
            color = QColor(engine.entry_type_color(key, dark=colors.dark, category=self._categories[index])
                           if key else segment_colors[index % len(segment_colors)])
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
