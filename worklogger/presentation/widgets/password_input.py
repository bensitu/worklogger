"""Password entry with an embedded, theme-aware visibility action."""

from PySide6.QtWidgets import QLineEdit

from worklogger.infrastructure.i18n import _
from worklogger.presentation.widgets.icons import ui_icon


class PasswordLineEdit(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEchoMode(QLineEdit.EchoMode.Password)
        self.visibility_action = self.addAction(ui_icon("eye"), QLineEdit.ActionPosition.TrailingPosition)
        self.visibility_action.setText(_("Show password"))
        self.visibility_action.triggered.connect(self._toggle_visibility)

    def _toggle_visibility(self):
        visible = self.echoMode() == QLineEdit.EchoMode.Password
        self.setEchoMode(QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password)
        self.visibility_action.setIcon(ui_icon("eye-off" if visible else "eye"))
        self.visibility_action.setText(_("Hide password") if visible else _("Show password"))
