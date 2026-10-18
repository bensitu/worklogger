"""Reusable metric card layout and width-constrained value labels."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont, QFontMetricsF, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from worklogger.presentation.widgets.card import CardFrame


class SummaryValueLabel(QLabel):
    """Keep a complete metric on one line without widening its card."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setWordWrap(False)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

    def fitted_font(self) -> QFont:
        font = QFont(self.font())
        available = max(1, self.contentsRect().width())
        while QFontMetricsF(font).horizontalAdvance(self.text()) > available:
            if font.pixelSize() > 1:
                font.setPixelSize(font.pixelSize() - 1)
            elif font.pixelSize() < 0 and font.pointSizeF() > 1:
                font.setPointSizeF(max(1, font.pointSizeF() - 0.5))
            else:
                break
        return font

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setFont(self.fitted_font())
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(self.contentsRect(), self.alignment(), self.text())
        painter.end()


class SummaryCard(CardFrame):
    def __init__(self, title: str, *, visual: QWidget | None = None, parent: QWidget | None = None,
                 object_name: str = "summary_card_frame") -> None:
        super().__init__(parent, object_name=object_name)
        self.content_layout.setContentsMargins(14, 10, 14, 10)
        self.content_layout.setSpacing(6)
        self.content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.title_label = QLabel(title)
        self.title_label.setProperty("role", "metric_title")
        self.title_label.setWordWrap(True)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.value_label = SummaryValueLabel()
        self.value_label.setProperty("role", "metric_value")
        self.caption_label = QLabel("")
        self.caption_label.setProperty("role", "metric_caption")
        self.caption_label.setWordWrap(True)
        self.content_layout.addWidget(self.title_label)
        if visual is None:
            self.content_layout.addWidget(self.value_label)
            self.content_layout.addWidget(self.caption_label)
        else:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            text = QVBoxLayout()
            text.setContentsMargins(0, 0, 0, 0)
            text.setSpacing(6)
            text.setAlignment(Qt.AlignmentFlag.AlignTop)
            text.addWidget(self.value_label)
            text.addWidget(self.caption_label)
            row.addLayout(text, 1)
            row.addWidget(visual)
            self.content_layout.addLayout(row)
