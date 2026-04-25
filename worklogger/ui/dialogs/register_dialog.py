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


class RegisterDialog(QDialog):
    def __init__(self, auth_service, parent=None):
        super().__init__(parent)
        self._auth = auth_service
        self.username: str | None = None

        self.setWindowTitle(_("Register"))
        self.setMinimumWidth(360)

        root = QVBoxLayout(self)
        form = QFormLayout()
        self._username = QLineEdit()
        self._password = QLineEdit()
        self._confirm = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._confirm.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(_("Username"), self._username)
        form.addRow(_("Password"), self._password)
        form.addRow(_("Confirm Password"), self._confirm)
        root.addLayout(form)

        row = QHBoxLayout()
        cancel_btn = QPushButton(_("Cancel"))
        register_btn = QPushButton(_("Register"))
        register_btn.setObjectName("primary_btn")
        row.addStretch()
        row.addWidget(cancel_btn)
        row.addWidget(register_btn)
        root.addLayout(row)

        cancel_btn.clicked.connect(self.reject)
        register_btn.clicked.connect(self._register)
        self._confirm.returnPressed.connect(self._register)

    def _register(self) -> None:
        username = self._username.text().strip()
        password = self._password.text()
        confirm = self._confirm.text()
        if not username:
            QMessageBox.warning(self, _("Register"), _("Username is required."))
            return
        if len(password) < 6:
            QMessageBox.warning(
                self,
                _("Register"),
                _("Password must be at least 6 characters."),
            )
            return
        if password != confirm:
            QMessageBox.warning(self, _("Register"), _("Passwords do not match."))
            return
        try:
            self._auth.register(username, password)
        except ValueError as exc:
            if str(exc) == "username_exists":
                text = _("Username already exists.")
            else:
                text = _("Registration failed.")
            QMessageBox.warning(self, _("Register"), text)
            return
        self.username = username
        QMessageBox.information(
            self,
            _("Register"),
            _("Registration successful. Please log in."),
        )
        self.accept()
