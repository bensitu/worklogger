"""Dashboard progress card widgets."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from worklogger.presentation.widgets.card import CardFrame


class DonutGauge(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("donut_gauge_widget")
        self._progress = 0.0
        self.setFixedSize(76, 76)

    def set_progress(self, progress: float) -> None:
        self._progress = max(0.0, min(1.0, float(progress or 0.0)))
        self.update()

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(8, 8, self.width() - 16, self.height() - 16)
        painter.setPen(QPen(QColor("#dce3ef"), 8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(rect, 0, 360 * 16)
        painter.setPen(QPen(QColor("#1a73e8"), 8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(rect, 90 * 16, -int(360 * 16 * self._progress))
        painter.setPen(QColor("#111827"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{round(self._progress * 100)}%")
        painter.end()


class DonutProgressCard(CardFrame):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent, object_name="donut_progress_card_frame")
        self.title_label = QLabel(title)
        self.title_label.setObjectName("donut_title_label")
        self.value_label = QLabel("")
        self.value_label.setObjectName("donut_value_label")
        self.caption_label = QLabel("")
        self.caption_label.setObjectName("donut_caption_label")
        self.caption_label.setProperty("role", "secondary")
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
        self.value_label = QLabel("")
        self.value_label.setObjectName("dot_value_label")
        self.caption_label = QLabel("")
        self.caption_label.setObjectName("dot_caption_label")
        self.caption_label.setProperty("role", "secondary")
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
        spacing = 10
        radius = 4
        for index in range(self._total):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._color if index < self._filled else QColor("#d0d7e2"))
            painter.drawEllipse(index * spacing, 4, radius * 2, radius * 2)
        painter.end()

