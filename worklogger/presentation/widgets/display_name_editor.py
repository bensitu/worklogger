"""Inline profile-name editing with explicit save and cancel actions."""

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QToolButton, QVBoxLayout, QWidget

from worklogger.infrastructure.i18n import _
from worklogger.presentation.widgets.icons import set_button_icon
from worklogger.presentation.widgets.status_label import StatusLabel
from worklogger.presentation.widgets._style import refresh_style


class DisplayNameEditor(QWidget):
    save_requested = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("account_display_name_editor_widget")
        self._saved_name = ""
        self._login_id = ""
        self._effective_name = ""
        self._expected_name = ""
        self._editing = False
        self._busy = False
        self._available = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.input = QLineEdit()
        self.input.setObjectName("account_name_line_edit")
        self.input.setMaxLength(80)
        self.input.setAccessibleName(_("Display name"))
        self.input.installEventFilter(self)
        self.input.textChanged.connect(self._update_actions)
        row.addWidget(self.input, 1)
        self.edit_button = self._button("pencil", _("Edit display name"))
        self.save_button = self._button("check", _("Save display name"))
        self.cancel_button = self._button("x", _("Cancel"))
        self.edit_button.clicked.connect(self.begin_editing)
        self.save_button.clicked.connect(self._save)
        self.cancel_button.clicked.connect(self.cancel_editing)
        for button in (self.edit_button, self.save_button, self.cancel_button):
            row.addWidget(button)
        layout.addLayout(row)
        self.error_label = StatusLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.error_label)
        self._escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._escape.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._escape.activated.connect(self.cancel_editing)
        self._update_actions()

    def _button(self, icon, caption):
        button = QToolButton()
        button.setFixedSize(40, 40)
        button.setObjectName("display_name_action_button")
        button.setToolTip(caption)
        button.setAccessibleName(caption)
        set_button_icon(button, icon)
        return button

    @property
    def has_unsaved_changes(self):
        return self._editing and self.input.text() != self._expected_name

    def set_available(self, available):
        self._available = available
        self._update_actions()

    def set_profile(self, user):
        self._login_id = user.username
        self._saved_name = user.display_name
        self._effective_name = user.effective_display_name
        self.input.setPlaceholderText(user.username)
        if not self._editing:
            self.input.setText(user.effective_display_name)

    def begin_editing(self):
        if self._busy or not self._available:
            return
        self._expected_name = self._saved_name
        self._editing = True
        self.input.setText(self._saved_name)
        self.error_label.clear()
        self._update_actions()
        self.input.setFocus()
        self.input.selectAll()

    def cancel_editing(self):
        if self._busy:
            return
        self._editing = False
        self.input.setText(self._effective_name)
        self.error_label.clear()
        self._update_actions()
        if self._available:
            self.edit_button.setFocus()

    def complete_save(self, user):
        self._editing = False
        self.error_label.clear()
        self.set_profile(user)
        self._update_actions()
        self.edit_button.setFocus()

    def set_busy(self, busy):
        self._busy = busy
        self._update_actions()

    def set_error(self, message):
        self.error_label.setText(message)

    def _save(self):
        if self._editing and not self._busy and self.has_unsaved_changes:
            self.save_requested.emit(self.input.text(), self._expected_name)

    def _update_actions(self, *_args):
        read_only = not self._editing or self._busy
        if self.input.isReadOnly() != read_only:
            self.input.setReadOnly(read_only)
            refresh_style(self.input)
        self.edit_button.setVisible(not self._editing and self._available)
        self.edit_button.setEnabled(not self._busy)
        self.save_button.setVisible(self._editing)
        self.cancel_button.setVisible(self._editing)
        self.save_button.setEnabled(not self._busy and self.has_unsaved_changes)
        self.cancel_button.setEnabled(not self._busy)
        if hasattr(self, "_escape"):
            self._escape.setEnabled(self._editing and not self._busy)

    def eventFilter(self, watched, event):
        if watched is self.input and self._editing and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.cancel_editing()
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._save()
                return True
        return super().eventFilter(watched, event)
