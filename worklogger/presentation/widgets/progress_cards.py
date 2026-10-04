"""Dashboard progress card widgets."""

from __future__ import annotations

from math import isfinite

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from worklogger.infrastructure.i18n import _
from worklogger.presentation.widgets.card import CardFrame
from worklogger.presentation.widgets.combo_chart import chart_palette


class DonutGauge(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("donut_gauge_widget")
        self._progress = 0.0
        self.setFixedSize(80, 80)

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
        rect = QRectF(16, 16, self.width() - 32, self.height() - 32)
        colors = chart_palette(self)
        painter.setPen(QPen(QColor(colors.border), 8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(rect, 0, 360 * 16)
        painter.setPen(QPen(QColor(colors.accent), 8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(rect, 90 * 16, -int(360 * 16 * min(self._progress, 1.0)))
        if self._progress > 1.0:
            outer = QRectF(5, 5, self.width() - 10, self.height() - 10)
            painter.setPen(QPen(QColor(colors.border), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(outer, 0, 360 * 16)
            overflow_color = QColor(colors.warning)
            accent_hue = QColor(colors.accent).hueF()
            hue_distance = abs(accent_hue - overflow_color.hueF())
            if accent_hue >= 0 and min(hue_distance, 1 - hue_distance) < 0.12:
                overflow_color = QColor(colors.success)
            painter.setPen(QPen(overflow_color, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(outer, 90 * 16, -int(360 * 16 * min(self._progress - 1.0, 1.0)))
        font = painter.font()
        font.setPixelSize(13)
        text = self.percentage_text
        while QFontMetricsF(font).horizontalAdvance(text) > rect.width() - 12 and font.pixelSize() > 8:
            font.setPixelSize(font.pixelSize() - 1)
        painter.setFont(font)
        painter.setPen(QColor(colors.text))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.end()


class DonutProgressCard(CardFrame):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent, object_name="donut_progress_card_frame")
        self.title_label = QLabel(title)
        self.title_label.setObjectName("donut_title_label")
        self.title_label.setWordWrap(True)
        self.value_label = QLabel("")
        self.value_label.setObjectName("donut_value_label")
        self.value_label.setWordWrap(True)
        self.caption_label = QLabel("")
        self.caption_label.setObjectName("donut_caption_label")
        self.caption_label.setProperty("role", "secondary")
        self.caption_label.setWordWrap(True)
        self.gauge = DonutGauge()

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.addWidget(self.title_label)
        text.addWidget(self.value_label)
        text.addWidget(self.caption_label)
        row.addLayout(text, 1)
        row.addWidget(self.gauge)
        self.content_layout.addLayout(row)

    def set_value(self, value: str, caption: str, progress: float) -> None:
        self.value_label.setText(value)
        self.caption_label.setText(caption)
        self.gauge.set_progress(progress)


class DotProgressCard(CardFrame):
    def __init__(self, title: str, *, color: str = "#16a34a", parent: QWidget | None = None) -> None:
        super().__init__(parent, object_name="dot_progress_card_frame")
        self._color = color
        self.title_label = QLabel(title)
        self.title_label.setObjectName("dot_title_label")
        self.title_label.setWordWrap(True)
        self.value_label = QLabel("")
        self.value_label.setObjectName("dot_value_label")
        self.caption_label = QLabel("")
        self.caption_label.setObjectName("dot_caption_label")
        self.caption_label.setProperty("role", "secondary")
        self.caption_label.setWordWrap(True)
        self.dots_widget = _DotsWidget(color=color)
        self.content_layout.addWidget(self.title_label)
        self.content_layout.addWidget(self.value_label)
        self.content_layout.addWidget(self.caption_label)
        self.content_layout.addWidget(self.dots_widget)

    def set_value(self, value: str, caption: str, filled: int, total: int = 12) -> None:
        self.value_label.setText(value)
        self.caption_label.setText(caption)
        self.dots_widget.set_progress(filled, total)


class _DotsWidget(QWidget):
    def __init__(self, *, color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dots_progress_widget")
        self._color = QColor(color)
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
        colors = chart_palette(self)
        for index in range(visible):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._color if index < filled else QColor(colors.border_strong))
            painter.drawEllipse(QRectF(index * spacing, 4, radius * 2, radius * 2))
        painter.end()

