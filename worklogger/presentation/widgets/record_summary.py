"""Selectable record text with a marker aligned to its first line."""

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy
from worklogger.presentation.widgets.hover_delete_button import HoverDeleteButton


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


class RecordSummaryButton(HoverDeleteButton):
    def __init__(self, text: str, *, deletable: bool = False):
        super().__init__(deletable=deletable)
        self.setObjectName("calendar_time_entry_button")
        self.delete_button.setAccessibleName(self.delete_button.toolTip() + ": " + text)
        self.label = RecordSummaryLabel(text)
        self.label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 8, 42 if deletable else 8, 8)
        row.addWidget(self.label)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return max(60, self.label.heightForWidth(max(1, width - (50 if self._deletable else 16))) + 16)

    def sizeHint(self):
        return QSize(180, self.heightForWidth(180))

    def minimumSizeHint(self):
        return QSize(80, 60)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        height = self.heightForWidth(self.width())
        if self.minimumHeight() != height:
            self.setMinimumHeight(height)
