"""Selectable record text with a marker aligned to its first line."""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QLabel


class RecordSummaryLabel(QLabel):
    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.setObjectName("calendar_record_label")
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setContentsMargins(12, 0, 0, 0)
        self.setIndent(0)
        self.marker = QLabel(self)
        self.marker.setObjectName("calendar_record_marker_label")
        self.marker.setFixedSize(6, 6)
        self._align_marker()

    def _align_marker(self) -> None:
        content = self.contentsRect()
        self.marker.move(content.x() - 12, content.y() + round((self.fontMetrics().height() - self.marker.height()) / 2))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._align_marker()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange) and hasattr(self, "marker"):
            self._align_marker()
