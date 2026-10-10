"""List-item deletion actions with stable mouse and keyboard interaction."""

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QPushButton, QToolButton

from worklogger.infrastructure.i18n import _
from worklogger.presentation.widgets.icons import set_button_icon


class HoverDeleteButton(QPushButton):
    delete_requested = Signal()
    hovered = Signal(object)

    def __init__(self, text="", parent=None, *, deletable=True, delete_label=None):
        super().__init__(text, parent)
        self._deletable = deletable
        self._keyboard_focus = False
        self.delete_button = QToolButton(self)
        self.delete_button.setObjectName("delete_record_button")
        self.delete_button.setProperty("variant", "danger")
        set_button_icon(self.delete_button, "trash")
        self.delete_button.setToolTip(delete_label or _("Delete record"))
        self.delete_button.setAccessibleName((delete_label or _("Delete record")) + ": " + text)
        self.delete_button.clicked.connect(self.delete_requested)
        self.delete_button.installEventFilter(self)
        self.delete_button.hide()

    def update_delete_visibility(self, position=None):
        focused = self._keyboard_focus and (self.hasFocus() or self.delete_button.hasFocus())
        hovered = self.rect().contains(self.mapFromGlobal(position or QCursor.pos()))
        self.delete_button.setVisible(self._deletable and (hovered or focused))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.delete_button.setGeometry(max(0, self.width() - 36), 8, 28, 28)

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update_delete_visibility()
        self.hovered.emit(self)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update_delete_visibility()

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._keyboard_focus = event.reason() in (
            Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason, Qt.FocusReason.ShortcutFocusReason)
        self.update_delete_visibility()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        QTimer.singleShot(0, self, self.update_delete_visibility)

    def eventFilter(self, watched, event):
        if watched is self.delete_button and event.type() == QEvent.Type.FocusIn:
            self._keyboard_focus = event.reason() in (
                Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason, Qt.FocusReason.ShortcutFocusReason)
        if watched is self.delete_button and event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            QTimer.singleShot(0, self, self.update_delete_visibility)
        return super().eventFilter(watched, event)
