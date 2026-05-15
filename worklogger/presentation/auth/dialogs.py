"""Login and registration dialogs."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from worklogger.infrastructure.i18n import _


@dataclass(frozen=True)
class LoginDraft:
    username: str
    password: str
    remember: bool


@dataclass(frozen=True)
class RegisterDraft:
    username: str
    password: str
    password_confirm: str


@dataclass(frozen=True)
class ResetPasswordDraft:
    username: str
    recovery_key: str
    new_password: str
    password_confirm: str


@dataclass(frozen=True)
class ChangePasswordDraft:
    current_password: str
    new_password: str
    password_confirm: str


class LoginDialog(QDialog):
    login_submitted = Signal(object)
    register_requested = Signal()
    reset_password_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("login_dialog")
        self.setWindowTitle(_("Login"))
        self._build_ui()

    def draft(self) -> LoginDraft:
        return LoginDraft(
            username=self.username_input.text(),
            password=self.password_input.text(),
            remember=self.remember_check.isChecked(),
        )

    def set_error(self, message: str) -> None:
        self.status_label.setText(message)

    def set_busy(self, busy: bool) -> None:
        self.login_button.setEnabled(not busy)
        self.register_button.setEnabled(not busy)
        self.reset_password_button.setEnabled(not busy)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel(_("Login"))
        title.setObjectName("login_title_label")
        root.addWidget(title)

        form = QFormLayout()
        root.addLayout(form)
        self.username_input = QLineEdit()
        self.username_input.setObjectName("username_line_edit")
        form.addRow(_("Username"), self.username_input)

        self.password_input = QLineEdit()
        self.password_input.setObjectName("password_line_edit")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(_("Password"), self.password_input)

        self.remember_check = QCheckBox(_("Remember me"))
        root.addWidget(self.remember_check)

        self.status_label = QLabel("")
        self.status_label.setObjectName("auth_status_label")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        buttons = QHBoxLayout()
        self.register_button = QPushButton(_("Create account"))
        self.reset_password_button = QPushButton(_("Reset password"))
        self.login_button = QPushButton(_("Login"))
        self.login_button.setObjectName("login_button")
        self.login_button.setProperty("variant", "primary")
        buttons.addWidget(self.register_button)
        buttons.addWidget(self.reset_password_button)
        buttons.addStretch(1)
        buttons.addWidget(self.login_button)
        root.addLayout(buttons)

        self.login_button.clicked.connect(lambda: self.login_submitted.emit(self.draft()))
        self.register_button.clicked.connect(self.register_requested.emit)
        self.reset_password_button.clicked.connect(self.reset_password_requested.emit)


class RegisterDialog(QDialog):
    register_submitted = Signal(object)
    login_requested = Signal()
    continue_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._registration_complete = False
        self.setObjectName("register_dialog")
        self.setWindowTitle(_("Create account"))
        self._build_ui()

    def draft(self) -> RegisterDraft:
        return RegisterDraft(
            username=self.username_input.text(),
            password=self.password_input.text(),
            password_confirm=self.confirm_input.text(),
        )

    def set_error(self, message: str) -> None:
        self.status_label.setText(message)

    def set_recovery_key(self, recovery_key: str) -> None:
        self.recovery_key_label.setText(recovery_key)
        self.recovery_key_label.setVisible(bool(recovery_key))
        self.recovery_key_caption.setVisible(bool(recovery_key))

    def mark_complete(self, recovery_key: str) -> None:
        self._registration_complete = True
        self.set_recovery_key(recovery_key)
        self.username_input.setEnabled(False)
        self.password_input.setEnabled(False)
        self.confirm_input.setEnabled(False)
        self.login_button.setEnabled(False)
        self.register_button.setText(_("Continue"))
        self.register_button.setEnabled(True)

    def set_busy(self, busy: bool) -> None:
        self.register_button.setEnabled(not busy)
        self.login_button.setEnabled(False if self._registration_complete else not busy)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel(_("Create account"))
        title.setObjectName("register_title_label")
        root.addWidget(title)

        form = QFormLayout()
        root.addLayout(form)
        self.username_input = QLineEdit()
        self.username_input.setObjectName("username_line_edit")
        form.addRow(_("Username"), self.username_input)

        self.password_input = QLineEdit()
        self.password_input.setObjectName("password_line_edit")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(_("Password"), self.password_input)

        self.confirm_input = QLineEdit()
        self.confirm_input.setObjectName("confirm_password_line_edit")
        self.confirm_input.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(_("Confirm password"), self.confirm_input)

        self.status_label = QLabel("")
        self.status_label.setObjectName("auth_status_label")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        self.recovery_key_caption = QLabel(_("Recovery key"))
        self.recovery_key_caption.setObjectName("recovery_key_caption_label")
        self.recovery_key_label = QLabel("")
        self.recovery_key_label.setObjectName("recovery_key_label")
        self.recovery_key_label.setWordWrap(True)
        self.recovery_key_caption.setVisible(False)
        self.recovery_key_label.setVisible(False)
        root.addWidget(self.recovery_key_caption)
        root.addWidget(self.recovery_key_label)

        buttons = QHBoxLayout()
        self.login_button = QPushButton(_("Back to login"))
        self.register_button = QPushButton(_("Create account"))
        self.register_button.setObjectName("register_button")
        self.register_button.setProperty("variant", "primary")
        buttons.addWidget(self.login_button)
        buttons.addStretch(1)
        buttons.addWidget(self.register_button)
        root.addLayout(buttons)

        self.register_button.clicked.connect(self._handle_register_clicked)
        self.login_button.clicked.connect(self.login_requested.emit)

    def _handle_register_clicked(self) -> None:
        if self._registration_complete:
            self.continue_requested.emit()
            return
        self.register_submitted.emit(self.draft())


class ResetPasswordDialog(QDialog):
    reset_submitted = Signal(object)
    login_requested = Signal()
    continue_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._reset_complete = False
        self.setObjectName("reset_password_dialog")
        self.setWindowTitle(_("Reset password"))
        self._build_ui()

    def draft(self) -> ResetPasswordDraft:
        return ResetPasswordDraft(
            username=self.username_input.text(),
            recovery_key=self.recovery_key_input.text(),
            new_password=self.password_input.text(),
            password_confirm=self.confirm_input.text(),
        )

    def set_error(self, message: str) -> None:
        self.status_label.setText(message)

    def set_recovery_key(self, recovery_key: str) -> None:
        self.recovery_key_result_label.setText(recovery_key)
        self.recovery_key_result_label.setVisible(bool(recovery_key))
        self.recovery_key_caption.setVisible(bool(recovery_key))

    def mark_complete(self, recovery_key: str) -> None:
        self._reset_complete = True
        self.set_recovery_key(recovery_key)
        self.username_input.setEnabled(False)
        self.recovery_key_input.setEnabled(False)
        self.password_input.setEnabled(False)
        self.confirm_input.setEnabled(False)
        self.login_button.setEnabled(False)
        self.reset_button.setText(_("Back to login"))
        self.reset_button.setEnabled(True)

    def set_busy(self, busy: bool) -> None:
        self.reset_button.setEnabled(not busy)
        self.login_button.setEnabled(False if self._reset_complete else not busy)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel(_("Reset password"))
        title.setObjectName("reset_password_title_label")
        root.addWidget(title)

        form = QFormLayout()
        root.addLayout(form)
        self.username_input = QLineEdit()
        self.username_input.setObjectName("username_line_edit")
        form.addRow(_("Username"), self.username_input)

        self.recovery_key_input = QLineEdit()
        self.recovery_key_input.setObjectName("recovery_key_line_edit")
        form.addRow(_("Recovery key"), self.recovery_key_input)

        self.password_input = QLineEdit()
        self.password_input.setObjectName("new_password_line_edit")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(_("New password"), self.password_input)

        self.confirm_input = QLineEdit()
        self.confirm_input.setObjectName("confirm_password_line_edit")
        self.confirm_input.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(_("Confirm password"), self.confirm_input)

        self.status_label = QLabel("")
        self.status_label.setObjectName("auth_status_label")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        self.recovery_key_caption = QLabel(_("New recovery key"))
        self.recovery_key_caption.setObjectName("new_recovery_key_caption_label")
        self.recovery_key_result_label = QLabel("")
        self.recovery_key_result_label.setObjectName("recovery_key_label")
        self.recovery_key_result_label.setWordWrap(True)
        self.recovery_key_caption.setVisible(False)
        self.recovery_key_result_label.setVisible(False)
        root.addWidget(self.recovery_key_caption)
        root.addWidget(self.recovery_key_result_label)

        buttons = QHBoxLayout()
        self.login_button = QPushButton(_("Back to login"))
        self.reset_button = QPushButton(_("Reset password"))
        self.reset_button.setObjectName("reset_password_button")
        self.reset_button.setProperty("variant", "primary")
        buttons.addWidget(self.login_button)
        buttons.addStretch(1)
        buttons.addWidget(self.reset_button)
        root.addLayout(buttons)

        self.reset_button.clicked.connect(self._handle_reset_clicked)
        self.login_button.clicked.connect(self.login_requested.emit)

    def _handle_reset_clicked(self) -> None:
        if self._reset_complete:
            self.continue_requested.emit()
            return
        self.reset_submitted.emit(self.draft())


class ChangePasswordDialog(QDialog):
    change_submitted = Signal(object)
    continue_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._change_complete = False
        self.setObjectName("change_password_dialog")
        self.setWindowTitle(_("Change password"))
        self._build_ui()

    def draft(self) -> ChangePasswordDraft:
        return ChangePasswordDraft(
            current_password=self.current_password_input.text(),
            new_password=self.password_input.text(),
            password_confirm=self.confirm_input.text(),
        )

    def set_error(self, message: str) -> None:
        self.status_label.setText(message)

    def set_recovery_key(self, recovery_key: str) -> None:
        self.recovery_key_label.setText(recovery_key)
        self.recovery_key_label.setVisible(bool(recovery_key))
        self.recovery_key_caption.setVisible(bool(recovery_key))

    def mark_complete(self, recovery_key: str) -> None:
        self._change_complete = True
        self.set_recovery_key(recovery_key)
        self.current_password_input.setEnabled(False)
        self.password_input.setEnabled(False)
        self.confirm_input.setEnabled(False)
        self.change_button.setText(_("Continue"))
        self.change_button.setEnabled(True)

    def set_busy(self, busy: bool) -> None:
        self.change_button.setEnabled(not busy)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel(_("Change password"))
        title.setObjectName("change_password_title_label")
        root.addWidget(title)

        form = QFormLayout()
        root.addLayout(form)
        self.current_password_input = QLineEdit()
        self.current_password_input.setObjectName("current_password_line_edit")
        self.current_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(_("Current password"), self.current_password_input)

        self.password_input = QLineEdit()
        self.password_input.setObjectName("new_password_line_edit")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(_("New password"), self.password_input)

        self.confirm_input = QLineEdit()
        self.confirm_input.setObjectName("confirm_password_line_edit")
        self.confirm_input.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(_("Confirm password"), self.confirm_input)

        self.status_label = QLabel("")
        self.status_label.setObjectName("auth_status_label")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        self.recovery_key_caption = QLabel(_("New recovery key"))
        self.recovery_key_caption.setObjectName("new_recovery_key_caption_label")
        self.recovery_key_label = QLabel("")
        self.recovery_key_label.setObjectName("recovery_key_label")
        self.recovery_key_label.setWordWrap(True)
        self.recovery_key_caption.setVisible(False)
        self.recovery_key_label.setVisible(False)
        root.addWidget(self.recovery_key_caption)
        root.addWidget(self.recovery_key_label)

        buttons = QHBoxLayout()
        self.change_button = QPushButton(_("Change password"))
        self.change_button.setObjectName("change_password_button")
        self.change_button.setProperty("variant", "primary")
        buttons.addStretch(1)
        buttons.addWidget(self.change_button)
        root.addLayout(buttons)

        self.change_button.clicked.connect(self._handle_change_clicked)

    def _handle_change_clicked(self) -> None:
        if self._change_complete:
            self.continue_requested.emit()
            return
        self.change_submitted.emit(self.draft())
