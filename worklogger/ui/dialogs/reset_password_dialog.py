from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from utils.i18n import _


class ResetPasswordDialog(QDialog):
    def __init__(self, auth_service, *, username: str = "", parent=None):
        super().__init__(parent)
        self._auth = auth_service

        self.setWindowTitle(_("Reset Password"))
        self.setMinimumWidth(420)

        root = QVBoxLayout(self)
        form = QFormLayout()
        self._username = QLineEdit()
        self._username.setText(username)
        self._recovery_key = QLineEdit()
        self._new = QLineEdit()
        self._confirm = QLineEdit()
        for edit in (self._recovery_key, self._new, self._confirm):
            edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(_("Username"), self._username)
        form.addRow(_("Recovery Key"), self._recovery_key)
        form.addRow(_("New Password"), self._new)
        form.addRow(_("Confirm Password"), self._confirm)
        root.addLayout(form)

        row = QHBoxLayout()
        cancel_btn = QPushButton(_("Cancel"))
        reset_btn = QPushButton(_("Reset Password"))
        reset_btn.setObjectName("primary_btn")
        row.addStretch()
        row.addWidget(cancel_btn)
        row.addWidget(reset_btn)
        root.addLayout(row)

        cancel_btn.clicked.connect(self.reject)
        reset_btn.clicked.connect(self._reset)
        self._confirm.returnPressed.connect(self._reset)

    def _reset(self) -> None:
        username = self._username.text().strip()
        recovery_key = self._recovery_key.text().strip()
        new_pw = self._new.text()
        confirm = self._confirm.text()
        if not username or not recovery_key:
            QMessageBox.warning(
                self,
                _("Reset Password"),
                _("Please enter username and recovery key."),
            )
            return
        if len(new_pw) < 6:
            QMessageBox.warning(
                self,
                _("Reset Password"),
                _("Password must be at least 6 characters."),
            )
            return
        if new_pw != confirm:
            QMessageBox.warning(
                self,
                _("Reset Password"),
                _("Passwords do not match."),
            )
            return
        try:
            changed = self._auth.reset_password_with_recovery(
                username,
                recovery_key,
                new_pw,
            )
        except ValueError:
            QMessageBox.warning(
                self,
                _("Reset Password"),
                _("Password must be at least 6 characters."),
            )
            return
        if not changed:
            QMessageBox.warning(
                self,
                _("Reset Password"),
                _(
                    "Recovery key is incorrect. Contact an administrator to reset your password."
                ),
            )
            return
        QMessageBox.information(
            self,
            _("Reset Password"),
            _("Password reset successfully. Please log in with the new password."),
        )
        self.accept()
