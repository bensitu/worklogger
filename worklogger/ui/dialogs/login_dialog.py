from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from utils.i18n import _


class LoginDialog(QDialog):
    register_requested = Signal()
    change_password_requested = Signal()
    reset_password_requested = Signal()

    def __init__(self, services, parent=None):
        super().__init__(parent)
        self._services = services
        self.user_id: int | None = None
        self.username: str | None = None

        self.setWindowTitle(_("Login"))
        self.setMinimumWidth(360)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(8)
        self._username = QLineEdit()
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._remember = QCheckBox(_("Remember me"))
        form.addRow(_("Username"), self._username)
        form.addRow(_("Password"), self._password)
        form.addRow("", self._remember)
        root.addLayout(form)

        self._status = QLabel("")
        self._status.setObjectName("muted")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        row = QHBoxLayout()
        self._register_btn = QPushButton(_("Register"))
        self._change_btn = QPushButton(_("Change Password"))
        self._reset_btn = QPushButton(_("Forgot Password?"))
        self._login_btn = QPushButton(_("Login"))
        self._login_btn.setObjectName("primary_btn")
        self._login_btn.setDefault(True)
        for button in (self._register_btn, self._change_btn, self._reset_btn):
            button.setAutoDefault(False)
            button.setDefault(False)
        row.addWidget(self._register_btn)
        row.addWidget(self._change_btn)
        row.addWidget(self._reset_btn)
        row.addStretch()
        row.addWidget(self._login_btn)
        root.addLayout(row)

        self._login_btn.clicked.connect(self._login)
        self._register_btn.clicked.connect(self.register_requested.emit)
        self._change_btn.clicked.connect(self.change_password_requested.emit)
        self._reset_btn.clicked.connect(self.reset_password_requested.emit)
        self._password.returnPressed.connect(self._login)
        self._username.setFocus()

    def set_username(self, username: str) -> None:
        self._username.setText(username)
        self._password.setFocus()

    def current_username(self) -> str:
        return self._username.text().strip()

    def _login(self) -> None:
        username = self._username.text().strip()
        password = self._password.text()
        if not username or not password:
            QMessageBox.warning(
                self,
                _("Login"),
                _("Please enter username and password."),
            )
            return
        try:
            user_id = self._services.auth.login(
                username,
                password,
                remember=self._remember.isChecked(),
            )
        except ImportError as exc:
            message = str(exc)
            if "cryptography" in message:
                message = _(
                    "Remember-token encryption requires the 'cryptography' package. "
                    "Please install it via pip install cryptography."
                )
            QMessageBox.warning(
                self,
                _("Login failed"),
                message,
            )
            return
        except ValueError:
            QMessageBox.warning(
                self,
                _("Login failed"),
                _("Username or password is incorrect."),
            )
            return
        self.user_id = user_id
        self.username = username
        self.accept()
