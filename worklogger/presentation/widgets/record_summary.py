"""Selectable record text with a marker aligned to its first line."""

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QToolButton, QWidget
from PySide6.QtGui import QCursor
from worklogger.infrastructure.i18n import _
from worklogger.presentation.widgets.icons import ui_icon


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


class RecordSummaryButton(QPushButton):
    delete_requested = Signal()
    hovered = Signal(object)

    def __init__(self, text: str, *, deletable: bool = False):
        super().__init__()
        self.setObjectName("calendar_time_entry_button")
        self.label = RecordSummaryLabel(text)
        self.label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 8, 8, 8)
        row.addWidget(self.label)
        self.delete_button = QToolButton(self)
        self.delete_button.setObjectName("delete_record_button")
        self.delete_button.setIcon(ui_icon("trash"))
        self.delete_button.setToolTip(_("Delete record"))
        self.delete_button.setAccessibleName(_("Delete record") + ": " + text)
        self.delete_button.clicked.connect(self.delete_requested)
        self._deletable = deletable
        self._keyboard_focus = False
        self.delete_button.installEventFilter(self)
        if deletable:
            slot = QWidget(self)
            slot.setObjectName("record_delete_slot_widget")
            slot.setFixedSize(28, 28)
            self.delete_button.setParent(slot)
            self.delete_button.setGeometry(0, 0, 28, 28)
            row.addWidget(slot, 0, Qt.AlignmentFlag.AlignTop)
        self.delete_button.hide()
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

    def _show_delete(self, position=None):
        focused = self._keyboard_focus and (self.hasFocus() or self.delete_button.hasFocus())
        hovered = self.rect().contains(self.mapFromGlobal(position or QCursor.pos()))
        self.delete_button.setVisible(self._deletable and (hovered or focused))

    def enterEvent(self, event):
        super().enterEvent(event)
        self._show_delete()
        self.hovered.emit(self)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._show_delete()

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._keyboard_focus = event.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason, Qt.FocusReason.ShortcutFocusReason)
        self._show_delete()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        QTimer.singleShot(0, self, self._show_delete)

    def eventFilter(self, watched, event):
        if watched is self.delete_button and event.type() == QEvent.Type.FocusIn:
            self._keyboard_focus = event.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason, Qt.FocusReason.ShortcutFocusReason)
        if watched is self.delete_button and event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            QTimer.singleShot(0, self, self._show_delete)
        return super().eventFilter(watched, event)
