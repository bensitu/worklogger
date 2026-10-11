"""Theme-aware progress visuals independent of dashboard card layouts."""

from __future__ import annotations

from math import ceil, isfinite

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QWidget

from worklogger.infrastructure.i18n import _
from worklogger.presentation.theme.context import current_colors


class DonutGauge(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("donut_gauge_widget")
        self._progress = 0.0
        self.setFixedSize(72, 72)

    def set_progress(self, progress: float) -> None:
        value = float(progress or 0.0)
        self._progress = max(0.0, value) if isfinite(value) else 0.0
        self.setAccessibleName(self.percentage_text)
        self.setToolTip(self.percentage_text)
        self.update()

    @property
    def percentage_text(self) -> str:
        return _("{percent}%").format(percent=round(self._progress * 100))

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(13, 13, self.width() - 26, self.height() - 26)
        colors = current_colors()
        overflow_color = QColor(colors.warning)
        accent_hue = QColor(colors.accent).hueF()
        hue_distance = abs(accent_hue - overflow_color.hueF())
        if accent_hue >= 0 and min(hue_distance, 1 - hue_distance) < 0.12:
            overflow_color = QColor(colors.success)
        third_color = QColor(colors.success if overflow_color.name() != colors.success else colors.warning)
        ring_colors = (QColor(colors.accent), overflow_color, third_color, QColor(colors.danger))
        # Bound rendering work for extreme ratios while retaining the actual percentage.
        count = max(1, min(32, ceil(self._progress)))
        for index in range(count):
            if count <= 2:
                radius, stroke = (23, 8) if index == 0 else (32, 6)
            else:
                step = 14 / (count - 1)
                radius, stroke = 18 + step * index, min(5.5, step * 0.8)
            ring = QRectF(36 - radius, 36 - radius, radius * 2, radius * 2)
            if index == 0:
                rect = ring.adjusted(stroke / 2 + 2, 0, -stroke / 2 - 2, 0)
            painter.setPen(QPen(QColor(colors.border), stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(ring, 0, 360 * 16)
            filled = min(max(self._progress - index, 0), 1)
            if filled:
                painter.setPen(QPen(ring_colors[index % len(ring_colors)], stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.drawArc(ring, 90 * 16, -int(360 * 16 * filled))
        font = painter.font()
        font.setPixelSize(13)
        text = self.percentage_text
        while QFontMetricsF(font).horizontalAdvance(text) > rect.width() and font.pixelSize() > 8:
            font.setPixelSize(font.pixelSize() - 1)
        painter.setFont(font)
        painter.setPen(QColor(colors.text))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.end()


class OvertimeComparisonChart(QWidget):
    """Compare overtime in the previous and current periods on a shared scale."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("overtime_comparison_widget")
        self.setFixedSize(72, 72)
        self._current = 0.0
        self._previous = 0.0

    def set_hours(self, current: float, previous: float) -> None:
        self._current = max(0.0, current) if isfinite(current) else 0.0
        self._previous = max(0.0, previous) if isfinite(previous) else 0.0
        description = _("Overtime comparison: previous period {previous:.1f}h, current period {current:.1f}h").format(
            previous=self._previous, current=self._current,
        )
        self.setToolTip(description)
        self.setAccessibleName(description)
        self.update()

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = current_colors()
        maximum = max(self._previous, self._current)
        painter.setPen(QPen(QColor(colors.border_strong), 1))
        painter.drawLine(7, 62, 65, 62)
        painter.setPen(Qt.PenStyle.NoPen)
        for index, hours in enumerate((self._previous, self._current)):
            height = 50 * hours / maximum if maximum else 0
            if height > 0:
                painter.setBrush(QColor(colors.border_strong if index == 0 else colors.warning))
                painter.drawRoundedRect(QRectF(13 + index * 27, 61 - height, 18, height), 3, 3)
        painter.end()


class ProgressDots(QWidget):
    def __init__(self, *, color: str | None = None, color_role: str = "success", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dots_progress_widget")
        if color_role not in ("success", "muted_text", "accent", "danger", "warning"):
            raise ValueError("Unsupported progress color role")
        self._color = QColor(color) if color is not None else None
        self._color_role = color_role
        self._filled = 0
        self._total = 12
        self.setMinimumHeight(18)

    def set_progress(self, filled: int, total: int) -> None:
        self._total = max(1, int(total or 1))
        self._filled = max(0, min(self._total, int(filled or 0)))
        self.update()

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        visible = min(self._total, 26)
        filled = round(self._filled / self._total * visible)
        spacing = min(10.0, self.width() / visible)
        radius = min(4.0, spacing * 0.36)
        colors = current_colors()
        active = self._color if self._color is not None else QColor(getattr(colors, self._color_role))
        for index in range(visible):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(active if index < filled else QColor(colors.border_strong))
            painter.drawEllipse(QRectF(index * spacing, 4, radius * 2, radius * 2))
        painter.end()


