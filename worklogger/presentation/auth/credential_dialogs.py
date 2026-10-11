"""Account registration and password recovery interfaces."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from worklogger.infrastructure.i18n import _
from worklogger.presentation.auth.dialog_base import RecoveryKeyDialog
from worklogger.presentation.auth.models import ChangePasswordDraft, RegisterDraft, ResetPasswordDraft
from worklogger.presentation.widgets.assets import apply_window_icon
from worklogger.presentation.widgets.credential_actions import fit_credential_result


class RegisterDialog(RecoveryKeyDialog):
    register_submitted = Signal(object)
    login_requested = Signal()
    continue_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._registration_complete = False
        self.setObjectName("register_dialog")
        self.setWindowTitle(_("Create account"))
        apply_window_icon(self)
        self._build_ui()
        self.resize(480, 360)
        self.setMinimumWidth(440)

    def draft(self) -> RegisterDraft:
        return RegisterDraft(
            username=self.username_input.text(),
            password=self.password_input.text(),
            password_confirm=self.confirm_input.text(),
        )

    def mark_complete(self, recovery_key: str) -> None:
        self._registration_complete = True
        self.set_recovery_key(recovery_key)
        self.username_input.setEnabled(False)
        self.password_input.setEnabled(False)
        self.confirm_input.setEnabled(False)
        self.account_label.setText(_("Account: {username}").format(username=self.username_input.text()))
        self.account_label.show()
        self.password_input.clear()
        self.confirm_input.clear()
        self.password_fields.hide()
        self.login_button.setEnabled(False)
        self.register_button.setText(_("Continue"))
        self.register_button.setEnabled(True)
        fit_credential_result(self)

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

        self.account_label = QLabel()
        self.account_label.setTextFormat(Qt.TextFormat.PlainText)
        self.account_label.setWordWrap(True)
        self.account_label.hide()
        root.addWidget(self.account_label)
        self.password_fields = QWidget()
        form = QFormLayout(self.password_fields)
        form.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.password_fields)
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

        self._add_recovery_display(root, caption=_("Recovery key"),
                                   caption_name="recovery_key_caption_label")

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


class ResetPasswordDialog(RecoveryKeyDialog):
    reset_submitted = Signal(object)
    login_requested = Signal()
    continue_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._reset_complete = False
        self.setObjectName("reset_password_dialog")
        self.setWindowTitle(_("Reset password"))
        apply_window_icon(self)
        self._build_ui()
        self.resize(480, 400)
        self.setMinimumWidth(440)

    def draft(self) -> ResetPasswordDraft:
        return ResetPasswordDraft(
            username=self.username_input.text(),
            recovery_key=self.recovery_key_input.text(),
            new_password=self.password_input.text(),
            password_confirm=self.confirm_input.text(),
        )

    def mark_complete(self, recovery_key: str) -> None:
        self._reset_complete = True
        self.set_recovery_key(recovery_key)
        self.username_input.setEnabled(False)
        self.recovery_key_input.setEnabled(False)
        self.password_input.setEnabled(False)
        self.confirm_input.setEnabled(False)
        self.account_label.setText(_("Account: {username}").format(username=self.username_input.text()))
        self.account_label.show()
        self.password_input.clear()
        self.confirm_input.clear()
        self.recovery_key_input.clear()
        self.password_fields.hide()
        self.login_button.setEnabled(False)
        self.reset_button.setText(_("Back to login"))
        self.reset_button.setEnabled(True)
        fit_credential_result(self)

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

        self.account_label = QLabel()
        self.account_label.setTextFormat(Qt.TextFormat.PlainText)
        self.account_label.setWordWrap(True)
        self.account_label.hide()
        root.addWidget(self.account_label)
        self.password_fields = QWidget()
        form = QFormLayout(self.password_fields)
        form.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.password_fields)
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

        self._add_recovery_display(root, caption=_("New recovery key"),
                                   caption_name="new_recovery_key_caption_label")
        self.recovery_key_result_label = self.recovery_key_label

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


class ChangePasswordDialog(RecoveryKeyDialog):
    change_submitted = Signal(object)
    continue_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._change_complete = False
        self.setObjectName("change_password_dialog")
        self.setWindowTitle(_("Change password"))
        apply_window_icon(self)
        self._build_ui()
        self.resize(480, 360)
        self.setMinimumWidth(440)

    def draft(self) -> ChangePasswordDraft:
        return ChangePasswordDraft(
            current_password=self.current_password_input.text(),
            new_password=self.password_input.text(),
            password_confirm=self.confirm_input.text(),
        )

    def mark_complete(self, recovery_key: str) -> None:
        self._change_complete = True
        self.set_recovery_key(recovery_key)
        self.current_password_input.setEnabled(False)
        self.password_input.setEnabled(False)
        self.confirm_input.setEnabled(False)
        self.current_password_input.clear()
        self.password_input.clear()
        self.confirm_input.clear()
        self.password_fields.hide()
        self.change_button.setText(_("Continue"))
        self.change_button.setEnabled(True)
        fit_credential_result(self)

    def set_busy(self, busy: bool) -> None:
        self.change_button.setEnabled(not busy)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel(_("Changing password will reset the recovery key."))
        title.setObjectName("change_password_title_label")
        title.setWordWrap(True)
        root.addWidget(title)

        self.password_fields = QWidget()
        form = QFormLayout(self.password_fields)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(12)
        root.addWidget(self.password_fields)
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

        self._add_recovery_display(root, caption=_("New recovery key"),
                                   caption_name="new_recovery_key_caption_label")
        for label in (title, self.status_label, self.recovery_key_caption, self.recovery_key_label):
            label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        root.addStretch(1)

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
