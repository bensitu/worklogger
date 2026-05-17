"""Login and registration dialogs."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QIcon, QPainter, QPen, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QDialog,
    QApplication,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from worklogger.infrastructure.i18n import _
from worklogger.presentation.theme import ThemeEngine, install_bundled_fonts
from worklogger.presentation.widgets.assets import apply_window_icon, asset_path, pixmap_asset
from worklogger.presentation.widgets import SwitchButton


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
        self.hero_frame: QFrame | None = None
        self.form_frame: QFrame | None = None
        self.setObjectName("login_dialog")
        self.setWindowTitle(_("Login"))
        apply_window_icon(self)
        self.setFixedSize(880, 580)
        install_bundled_fonts()
        self._apply_default_theme()
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
        self.google_login_button.setEnabled(False)
        self.microsoft_login_button.setEnabled(False)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._sync_column_widths()

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        hero_frame = QFrame()
        self.hero_frame = hero_frame
        hero_frame.setObjectName("login_hero_frame")
        hero_frame.setMinimumWidth(0)
        hero_frame.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        hero_layout = QVBoxLayout(hero_frame)
        hero_layout.setContentsMargins(0, 0, 0, 0)
        self.hero_image_label = QLabel("")
        self.hero_image_label.setObjectName("login_hero_label")
        self.hero_image_label.setMinimumSize(0, 0)
        self.hero_image_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        hero = pixmap_asset("images/worklogger_login_image.webp")
        if not hero.isNull():
            self.hero_image_label.setPixmap(hero)
            self.hero_image_label.setScaledContents(True)
        hero_layout.addWidget(self.hero_image_label)
        root.addWidget(hero_frame, 1)

        form_frame = QFrame()
        self.form_frame = form_frame
        form_frame.setObjectName("login_form_frame")
        form_frame.setMinimumWidth(0)
        form_frame.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        form_root = QVBoxLayout(form_frame)
        form_root.setContentsMargins(68, 44, 68, 28)
        form_root.setSpacing(10)
        root.addWidget(form_frame, 1)

        title = QLabel(_("Welcome!"))
        title.setObjectName("login_title_label")
        title.setProperty("role", "title")
        form_root.addWidget(title)

        subtitle = QLabel(_("Sign in to your account"))
        subtitle.setObjectName("login_subtitle_label")
        subtitle.setProperty("role", "subtitle")
        form_root.addWidget(subtitle)

        form_root.addSpacing(6)

        username_label = QLabel(_("ID"))
        username_label.setObjectName("login_username_label")
        form_root.addWidget(username_label)
        self.username_input = QLineEdit()
        self.username_input.setObjectName("username_line_edit")
        self.username_input.setPlaceholderText(_("Enter your ID"))
        self.username_input.setMinimumHeight(36)
        form_root.addWidget(self.username_input)

        password_label = QLabel(_("Password"))
        password_label.setObjectName("login_password_label")
        form_root.addWidget(password_label)
        self.password_input = QLineEdit()
        self.password_input.setObjectName("password_line_edit")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText(_("Enter your password"))
        self.password_input.setMinimumHeight(36)
        self.password_visibility_action: QAction = self.password_input.addAction(
            _visibility_icon(False),
            QLineEdit.ActionPosition.TrailingPosition,
        )
        self.password_visibility_action.setToolTip(_("Show"))
        self.password_visibility_action.triggered.connect(self._toggle_password_visibility)
        form_root.addWidget(self.password_input)

        remember_row = QHBoxLayout()
        remember_row.setContentsMargins(0, 0, 0, 0)
        remember_label = QLabel(_("Remember me"))
        remember_label.setObjectName("remember_me_label")
        self.remember_check = SwitchButton()
        remember_row.addWidget(remember_label)
        remember_row.addStretch(1)
        remember_row.addWidget(self.remember_check)
        form_root.addLayout(remember_row)

        self.status_label = QLabel("")
        self.status_label.setObjectName("auth_status_label")
        self.status_label.setWordWrap(True)
        form_root.addWidget(self.status_label)

        self.login_button = QPushButton(_("Login"))
        self.login_button.setObjectName("login_button")
        self.login_button.setProperty("variant", "primary")
        self.login_button.setDefault(True)
        self.login_button.setAutoDefault(True)
        form_root.addWidget(self.login_button)

        secondary_buttons = QHBoxLayout()
        secondary_buttons.setContentsMargins(0, 0, 0, 0)
        self.register_button = QPushButton(_("Register"))
        self.register_button.setObjectName("register_account_button")
        self.register_button.setProperty("variant", "outline")
        self.reset_password_button = QPushButton(_("Forgot Password?"))
        self.reset_password_button.setObjectName("reset_password_button")
        self.reset_password_button.setProperty("variant", "ghost")
        self.register_button.setAutoDefault(False)
        self.reset_password_button.setAutoDefault(False)
        secondary_buttons.addWidget(self.register_button)
        secondary_buttons.addStretch(1)
        secondary_buttons.addWidget(self.reset_password_button)
        form_root.addLayout(secondary_buttons)

        divider = QLabel(_("or"))
        divider.setObjectName("login_divider_label")
        divider.setProperty("role", "secondary")
        divider.setAlignment(Qt.AlignmentFlag.AlignCenter)
        form_root.addWidget(divider)

        self.google_login_button = QPushButton(_("Sign in with Google"))
        self.google_login_button.setObjectName("google_login_button")
        google_icon = QIcon(str(asset_path("images/google.svg")))
        if not google_icon.isNull():
            self.google_login_button.setIcon(google_icon)
        self.google_login_button.setEnabled(False)
        form_root.addWidget(self.google_login_button)

        self.microsoft_login_button = QPushButton(_("Sign in with Microsoft"))
        self.microsoft_login_button.setObjectName("microsoft_login_button")
        microsoft_icon = QIcon(str(asset_path("images/microsoft.svg")))
        if not microsoft_icon.isNull():
            self.microsoft_login_button.setIcon(microsoft_icon)
        self.microsoft_login_button.setEnabled(False)
        form_root.addWidget(self.microsoft_login_button)
        form_root.addStretch(1)

        self._set_login_control_heights()
        self._sync_column_widths()
        self.login_button.clicked.connect(lambda: self.login_submitted.emit(self.draft()))
        self.register_button.clicked.connect(self.register_requested.emit)
        self.reset_password_button.clicked.connect(self.reset_password_requested.emit)

    def _toggle_password_visibility(self) -> None:
        was_visible = self.password_input.echoMode() == QLineEdit.EchoMode.Normal
        is_visible = not was_visible
        self.password_input.setEchoMode(
            QLineEdit.EchoMode.Normal if is_visible else QLineEdit.EchoMode.Password
        )
        self.password_visibility_action.setIcon(_visibility_icon(is_visible))
        self.password_visibility_action.setToolTip(_("Hide") if is_visible else _("Show"))

    def _set_login_control_heights(self) -> None:
        for button in (
            self.login_button,
            self.register_button,
            self.reset_password_button,
            self.google_login_button,
            self.microsoft_login_button,
        ):
            button.setMinimumHeight(36)

    def _sync_column_widths(self) -> None:
        if self.hero_frame is None or self.form_frame is None:
            return
        left_width = self.width() // 2
        self.hero_frame.setFixedWidth(left_width)
        self.form_frame.setFixedWidth(self.width() - left_width)

    def _apply_default_theme(self) -> None:
        application = QApplication.instance()
        if application is None:
            return
        engine = ThemeEngine()
        application.setPalette(engine.qt_palette())
        application.setStyleSheet(engine.application_stylesheet())


def _visibility_icon(password_visible: bool) -> QIcon:
    pixmap = QPixmap(20, 20)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(Qt.GlobalColor.gray)
    pen.setWidthF(1.8)
    painter.setPen(pen)
    painter.drawEllipse(3, 6, 14, 8)
    painter.drawEllipse(8, 9, 4, 4)
    if password_visible:
        painter.drawLine(4, 16, 16, 4)
    painter.end()
    return QIcon(pixmap)


class RegisterDialog(QDialog):
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
        apply_window_icon(self)
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
        apply_window_icon(self)
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
