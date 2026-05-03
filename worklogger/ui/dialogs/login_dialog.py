from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QSize, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.widgets import SwitchButton
from utils.i18n import _
from utils.paths import candidate_assets_dirs


def _image_asset_path(filename: str):
    for assets_dir in candidate_assets_dirs():
        path = assets_dir / "images" / filename
        if path.is_file():
            return path
    return None


def _identity_error_message(error: str) -> str:
    if error in {"identity_provider_not_configured", "identity_provider_unavailable"}:
        return _("Google sign-in is not configured.")
    if error == "identity_callback_timeout":
        return _("Sign-in canceled.")
    base = _("Could not complete sign-in.")
    if error:
        return base + "\n" + _("Details: {detail}").format(detail=error)
    return base


class _IdentityLoginBridge(QObject):
    done = Signal(bool, int, str, str)


class LoginDialog(QDialog):
    register_requested = Signal()
    change_password_requested = Signal()
    reset_password_requested = Signal()

    def __init__(self, services, parent=None):
        super().__init__(parent)
        self._services = services
        self.user_id: int | None = None
        self.username: str | None = None
        self._identity_bridge = _IdentityLoginBridge(self)

        self.setWindowTitle(_("Login"))
        self.setMinimumWidth(360)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(8)
        self._username = QLineEdit()
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._remember = SwitchButton()
        remember_wrap = QWidget()
        remember_layout = QHBoxLayout(remember_wrap)
        remember_layout.setContentsMargins(0, 0, 0, 0)
        remember_layout.addWidget(self._remember)
        remember_layout.addStretch()
        form.addRow(_("Username"), self._username)
        form.addRow(_("Password"), self._password)
        form.addRow(_("Remember me"), remember_wrap)
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

        oauth_row = QHBoxLayout()
        self._google_btn = QPushButton(_("Sign in with Google"))
        self._microsoft_btn = QPushButton(_("Sign in with Microsoft"))
        for button, filename in (
            (self._google_btn, "google.svg"),
            (self._microsoft_btn, "microsoft.svg"),
        ):
            icon_path = _image_asset_path(filename)
            if icon_path is not None:
                button.setIcon(QIcon(str(icon_path)))
                button.setIconSize(QSize(18, 18))
        oauth_row.addWidget(self._google_btn)
        oauth_row.addWidget(self._microsoft_btn)
        root.addLayout(oauth_row)
        self._microsoft_btn.setVisible(False)

        self._login_btn.clicked.connect(self._login)
        self._google_btn.clicked.connect(lambda: self._identity_login("google"))
        self._microsoft_btn.clicked.connect(lambda: self._identity_login("microsoft"))
        self._register_btn.clicked.connect(self.register_requested.emit)
        self._change_btn.clicked.connect(self.change_password_requested.emit)
        self._reset_btn.clicked.connect(self.reset_password_requested.emit)
        self._password.returnPressed.connect(self._login)
        self._identity_bridge.done.connect(self._identity_done)
        self._username.setFocus()
        self._refresh_identity_buttons()

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

    def _refresh_identity_buttons(self) -> None:
        configured = False
        try:
            configured = self._services.identity_provider_available("google")
        except Exception:
            configured = False
        self._google_btn.setEnabled(configured)
        self._google_btn.setToolTip(
            "" if configured else _("Google sign-in is not configured.")
        )

    def _set_identity_busy(self, busy: bool) -> None:
        for widget in (
            self._username,
            self._password,
            self._remember,
            self._login_btn,
            self._register_btn,
            self._change_btn,
            self._reset_btn,
            self._google_btn,
            self._microsoft_btn,
        ):
            widget.setEnabled(not busy)
        if not busy:
            self._refresh_identity_buttons()

    def _identity_login(self, provider: str) -> None:
        self._set_identity_busy(True)
        self._status.setText(_("Opening browser..."))
        remember = self._remember.isChecked()

        def _worker() -> None:
            try:
                user_id = self._services.login_with_identity_provider(
                    provider,
                    remember=remember,
                )
                username = self._services.current_username or ""
                self._identity_bridge.done.emit(True, user_id, username, "")
            except Exception as exc:
                self._identity_bridge.done.emit(False, 0, "", str(exc))

        threading.Thread(target=_worker, daemon=True).start()

    def _identity_done(self, ok: bool, user_id: int, username: str, error: str) -> None:
        self._set_identity_busy(False)
        if ok:
            self.user_id = user_id
            self.username = username
            self._status.setText(_("Sign-in completed."))
            self.accept()
            return
        self._status.setText(_identity_error_message(error))
        QMessageBox.warning(self, _("Login failed"), self._status.text())
