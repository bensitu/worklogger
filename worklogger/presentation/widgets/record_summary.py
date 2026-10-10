"""Selectable record text with a marker aligned to its first line."""

from PySide6.QtCore import QEvent, QSize, Qt, Signal, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QToolButton
from worklogger.presentation.widgets.hover_delete_button import HoverDeleteButton
from worklogger.presentation.widgets.icons import ui_icon
from worklogger.infrastructure.i18n import _


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
    actions_requested = Signal(object)

    def __init__(self, text: str, *, deletable: bool = False, actions_enabled=False):
        super().__init__(deletable=deletable)
        self._actions_enabled = actions_enabled
        self.actions_button = QToolButton(self)
        self.actions_button.setObjectName("record_actions_button")
        self.actions_button.setIcon(ui_icon("chevron-down"))
        self.actions_button.setToolTip(_("Record actions"))
        self.actions_button.setAccessibleName(_("Record actions") + ": " + text)
        self.actions_button.clicked.connect(lambda: self.actions_requested.emit(self.actions_button.mapToGlobal(self.actions_button.rect().bottomLeft())))
        self.actions_button.installEventFilter(self)
        self.actions_button.hide()
        if actions_enabled:
            self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.customContextMenuRequested.connect(lambda position: self.actions_requested.emit(self.mapToGlobal(position)))
        self.setObjectName("calendar_time_entry_button")
        self.delete_button.setAccessibleName(self.delete_button.toolTip() + ": " + text)
        self.label = RecordSummaryLabel(text)
        self.label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row = QHBoxLayout(self)
        self._right_margin = 74 if deletable and actions_enabled else 42 if deletable or actions_enabled else 8
        row.setContentsMargins(8, 8, self._right_margin, 8)
        row.addWidget(self.label)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return max(60, self.label.heightForWidth(max(1, width - self._right_margin - 8)) + 16)

    def sizeHint(self):
        return QSize(180, self.heightForWidth(180))

    def minimumSizeHint(self):
        return QSize(80, 60)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.actions_button.setGeometry(max(0, self.width() - (68 if self._deletable else 36)), 8, 28, 28)
        height = self.heightForWidth(self.width())
        if self.minimumHeight() != height:
            self.setMinimumHeight(height)

    def update_delete_visibility(self, position=None):
        super().update_delete_visibility(position)
        if hasattr(self, "actions_button"):
            hovered = self.rect().contains(self.mapFromGlobal(position or QCursor.pos()))
            focused = self._keyboard_focus and (self.hasFocus() or self.delete_button.hasFocus() or self.actions_button.hasFocus())
            self.actions_button.setVisible(self._actions_enabled and (hovered or focused))

    def eventFilter(self, watched, event):
        actions_button = getattr(self, "actions_button", None)
        if watched is actions_button and event.type() == QEvent.Type.FocusIn:
            self._keyboard_focus = event.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason, Qt.FocusReason.ShortcutFocusReason)
        if watched is actions_button and event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            QTimer.singleShot(0, self, self.update_delete_visibility)
        return super().eventFilter(watched, event)
