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

from config.constants import PASSWORD_MIN_LENGTH
from utils.i18n import _


class ChangePasswordDialog(QDialog):
    def __init__(
        self,
        auth_service,
        *,
        current_user_id: int | None = None,
        username: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._auth = auth_service
        self._current_user_id = current_user_id
        self.setWindowTitle(_("Change Password"))
        self.setMinimumWidth(380)

        root = QVBoxLayout(self)
        form = QFormLayout()
        self._username = QLineEdit()
        self._username.setText(username)
        if current_user_id is not None:
            self._username.hide()
        self._old = QLineEdit()
        self._new = QLineEdit()
        self._confirm = QLineEdit()
        for edit in (self._old, self._new, self._confirm):
            edit.setEchoMode(QLineEdit.EchoMode.Password)
        if current_user_id is None:
            form.addRow(_("Username"), self._username)
        form.addRow(_("Old Password"), self._old)
        form.addRow(_("New Password"), self._new)
        form.addRow(_("Confirm Password"), self._confirm)
        root.addLayout(form)

        row = QHBoxLayout()
        cancel_btn = QPushButton(_("Cancel"))
        save_btn = QPushButton(_("Save"))
        save_btn.setObjectName("primary_btn")
        row.addStretch()
        row.addWidget(cancel_btn)
        row.addWidget(save_btn)
        root.addLayout(row)

        cancel_btn.clicked.connect(self.reject)
        save_btn.clicked.connect(self._change)
        self._confirm.returnPressed.connect(self._change)

    def _change(self) -> None:
        old_pw = self._old.text()
        new_pw = self._new.text()
        confirm = self._confirm.text()
        if len(new_pw) < PASSWORD_MIN_LENGTH:
            QMessageBox.warning(
                self,
                _("Change Password"),
                _("Password must be at least 8 characters."),
            )
            return
        if new_pw != confirm:
            QMessageBox.warning(
                self,
                _("Change Password"),
                _("Passwords do not match."),
            )
            return
        try:
            if self._current_user_id is not None:
                changed = self._auth.change_password(
                    self._current_user_id,
                    old_pw,
                    new_pw,
                )
            else:
                username = self._username.text().strip()
                if not username:
                    QMessageBox.warning(
                        self,
                        _("Change Password"),
                        _("Username is required."),
                    )
                    return
                changed = self._auth.change_password_for_username(
                    username,
                    old_pw,
                    new_pw,
                )
        except ValueError:
            QMessageBox.warning(
                self,
                _("Change Password"),
                _("Password must be at least 8 characters."),
            )
            return
        if not changed:
            QMessageBox.warning(
                self,
                _("Change Password"),
                _("Old password is incorrect."),
            )
            return
        QMessageBox.information(
            self,
            _("Change Password"),
            _("Password changed successfully."),
        )
        self.accept()
