"""Authentication dialog completion rules and shared credential display."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel

from worklogger.presentation.widgets.credential_actions import CredentialActions


class AuthDialog(QDialog):
    def done(self, result):
        request = getattr(self, "_authorization_request", None)
        if request is not None and request.is_running:
            self._authorization_close_result = result
            request.cancel()
            return
        if not getattr(self, "_auth_request_pending", False):
            super().done(result)



class RecoveryKeyDialog(AuthDialog):
    def set_error(self, message: str) -> None:
        self.status_label.setText(message)

    def set_recovery_key(self, recovery_key: str) -> None:
        self.recovery_key_label.setText(recovery_key)
        for widget in (self.recovery_key_label, self.recovery_key_caption, self.recovery_actions):
            widget.setVisible(bool(recovery_key))

    def _add_recovery_display(self, layout, *, caption, caption_name):
        self.recovery_key_caption = QLabel(caption)
        self.recovery_key_caption.setObjectName(caption_name)
        self.recovery_key_label = QLabel("")
        self.recovery_key_label.setObjectName("recovery_key_label")
        self.recovery_key_label.setWordWrap(True)
        self.recovery_key_label.setTextFormat(Qt.TextFormat.PlainText)
        self.recovery_key_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.recovery_actions = CredentialActions(self.recovery_key_label.text, self)
        for widget in (self.recovery_key_caption, self.recovery_key_label, self.recovery_actions):
            widget.hide()
            layout.addWidget(widget)
