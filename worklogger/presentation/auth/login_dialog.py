"""Local and external-provider sign-in interface."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QIcon, QResizeEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from worklogger.__about__ import APP_NAME
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_code
from worklogger.presentation.auth.dialog_base import AuthDialog
from worklogger.presentation.auth.models import LoginDraft
from worklogger.presentation.theme import ThemeEngine, configure_application_style, install_bundled_fonts
from worklogger.presentation.widgets import SwitchButton
from worklogger.presentation.widgets.assets import apply_window_icon, asset_path, pixmap_asset
from worklogger.presentation.widgets.icons import set_button_icon, ui_icon
from worklogger.presentation.widgets.processing_progress import ProcessingProgress
from worklogger.presentation.widgets.status_label import StatusLabel


class LoginDialog(AuthDialog):
    login_submitted = Signal(object)
    register_requested = Signal()
    reset_password_requested = Signal()
    identity_login_requested = Signal(str)
    identity_configuration_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.hero_frame: QFrame | None = None
        self._identity_availability = {}
        self._busy = False
        self._self_registration_enabled = True
        self._oidc_enabled = True
        self.form_frame: QFrame | None = None
        self.form_scroll: QScrollArea | None = None
        self.setObjectName("login_dialog")
        self.setWindowTitle(APP_NAME)
        apply_window_icon(self)
        self.setMinimumSize(420, 320)
        configure_application_style()
        install_bundled_fonts()
        self._apply_default_theme()
        self._build_ui()
        screen = self.screen()
        bounds = screen.availableGeometry() if screen is not None else None
        self.resize(min(880, max(420, bounds.width() - 48)) if bounds is not None else 880,
                    min(640, max(320, bounds.height() - 48)) if bounds is not None else 640)
        self._sync_column_widths()
        self.username_input.setFocus(Qt.FocusReason.OtherFocusReason)

    def draft(self) -> LoginDraft:
        return LoginDraft(
            username=self.username_input.text(),
            password=self.password_input.text(),
            remember=self.remember_check.isChecked(),
        )

    def set_error(self, message: str) -> None:
        self.status_label.setText(message)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.login_button.setEnabled(not busy)
        self.username_input.setEnabled(not busy)
        self.password_input.setEnabled(not busy)
        self.remember_check.setEnabled(not busy)
        self.register_button.setEnabled(not busy and self._self_registration_enabled)
        self.reset_password_button.setEnabled(not busy)
        for key, button in (("google", self.google_login_button), ("microsoft", self.microsoft_login_button)):
            button.setEnabled(not busy and self._oidc_enabled and self._identity_availability.get(key, False))
        for button in self.identity_configuration_buttons.values():
            button.setEnabled(not busy and self._oidc_enabled)

    def set_deployment_policy(self, *, self_registration_enabled: bool, oidc_enabled: bool) -> None:
        self._self_registration_enabled = self_registration_enabled
        self._oidc_enabled = oidc_enabled
        self.register_button.setToolTip("" if self_registration_enabled else display_error_code("self_registration_disabled"))
        for button in self.identity_configuration_buttons.values():
            button.setToolTip(_("Configure sign-in") if oidc_enabled else display_error_code("oidc_disabled"))
        self.set_busy(self._busy)

    def set_identity_providers(self, providers):
        self._identity_availability = {provider.provider: provider.available for provider in providers}
        for key, button in (("google", self.google_login_button), ("microsoft", self.microsoft_login_button)):
            button.setToolTip(display_error_code("oidc_disabled") if not self._oidc_enabled else
                              "" if self._identity_availability.get(key) else _("Configure this sign-in provider before continuing."))
        self.set_busy(self._busy)

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
        self.form_scroll = QScrollArea()
        self.form_scroll.setObjectName("login_form_scroll_area_widget")
        self.form_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.form_scroll.setWidgetResizable(True)
        self.form_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.form_scroll.setWidget(form_frame)
        root.addWidget(self.form_scroll, 1)

        title = QLabel(_("Welcome!"))
        title.setObjectName("login_title_label")
        title.setProperty("role", "title")
        form_root.addWidget(title)

        subtitle = QLabel(_("Sign in to your account"))
        subtitle.setObjectName("login_subtitle_label")
        subtitle.setProperty("role", "subtitle")
        form_root.addWidget(subtitle)

        form_root.addSpacing(6)

        credentials = QVBoxLayout()
        credentials.setSpacing(16)
        form_root.addLayout(credentials)
        username_group = QVBoxLayout()
        username_group.setSpacing(4)
        credentials.addLayout(username_group)
        username_label = QLabel(_("ID"))
        username_label.setObjectName("login_username_label")
        username_group.addWidget(username_label)
        self.username_input = QLineEdit()
        self.username_input.setObjectName("username_line_edit")
        self.username_input.setPlaceholderText(_("Enter your ID"))
        self.username_icon_action: QAction = self.username_input.addAction(
            ui_icon("user-round"),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        self.username_input.setMinimumHeight(36)
        username_group.addWidget(self.username_input)

        password_group = QVBoxLayout()
        password_group.setSpacing(4)
        credentials.addLayout(password_group)
        password_label = QLabel(_("Password"))
        password_label.setObjectName("login_password_label")
        password_group.addWidget(password_label)
        self.password_input = QLineEdit()
        self.password_input.setObjectName("password_line_edit")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText(_("Enter your password"))
        self.password_lock_action: QAction = self.password_input.addAction(
            ui_icon("lock-keyhole"),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        self.password_input.setMinimumHeight(36)
        self.password_visibility_action: QAction = self.password_input.addAction(
            _visibility_icon(False),
            QLineEdit.ActionPosition.TrailingPosition,
        )
        self.password_visibility_action.setToolTip(_("Show"))
        self.password_visibility_action.triggered.connect(self._toggle_password_visibility)
        password_group.addWidget(self.password_input)

        remember_row = QHBoxLayout()
        remember_row.setContentsMargins(0, 0, 0, 0)
        remember_label = QLabel(_("Remember me"))
        remember_label.setObjectName("remember_me_label")
        self.remember_check = SwitchButton()
        remember_row.addWidget(remember_label)
        remember_row.addStretch(1)
        remember_row.addWidget(self.remember_check)
        form_root.addLayout(remember_row)

        self.status_label = StatusLabel()
        self.status_label.setObjectName("auth_status_label")
        self.status_label.setWordWrap(True)
        self.auth_feedback_stack = QStackedWidget()
        self.auth_feedback_stack.setObjectName("authentication_feedback_stack_widget")
        self.auth_feedback_stack.addWidget(self.status_label)
        self.authorization_progress = ProcessingProgress()
        self.auth_feedback_stack.addWidget(self.authorization_progress)
        self.auth_feedback_stack.setCurrentWidget(self.status_label)
        form_root.addWidget(self.auth_feedback_stack)

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

        divider_row = QHBoxLayout()
        divider_row.setContentsMargins(0, 0, 0, 0)
        divider_row.setSpacing(10)
        left_rule = QFrame()
        left_rule.setObjectName("login_divider_left_frame")
        left_rule.setFrameShape(QFrame.Shape.HLine)
        right_rule = QFrame()
        right_rule.setObjectName("login_divider_right_frame")
        right_rule.setFrameShape(QFrame.Shape.HLine)
        divider = QLabel(_("or"))
        divider.setObjectName("login_divider_label")
        divider.setProperty("role", "secondary")
        divider.setAlignment(Qt.AlignmentFlag.AlignCenter)
        divider_row.addWidget(left_rule, 1)
        divider_row.addWidget(divider)
        divider_row.addWidget(right_rule, 1)
        form_root.addLayout(divider_row)

        self.google_login_button = QPushButton(_("Sign in with Google"))
        self.google_login_button.setObjectName("google_login_button")
        google_icon = QIcon(str(asset_path("images/google.svg")))
        if not google_icon.isNull():
            self.google_login_button.setIcon(google_icon)
        self.google_login_button.setEnabled(False)

        self.microsoft_login_button = QPushButton(_("Sign in with Microsoft"))
        self.microsoft_login_button.setObjectName("microsoft_login_button")
        microsoft_icon = QIcon(str(asset_path("images/microsoft.svg")))
        if not microsoft_icon.isNull():
            self.microsoft_login_button.setIcon(microsoft_icon)
        self.microsoft_login_button.setEnabled(False)
        self.identity_configuration_buttons = {}
        for key, button in (("google", self.google_login_button), ("microsoft", self.microsoft_login_button)):
            button.setAutoDefault(False)
            button.clicked.connect(lambda _checked=False, key=key: self.identity_login_requested.emit(key))
            row = QHBoxLayout()
            row.addWidget(button, 1)
            configure = QToolButton()
            configure.setObjectName("configure_identity_button")
            configure.setFixedSize(36, 36)
            configure.setToolTip(_("Configure sign-in") + " - " + button.text())
            configure.setAccessibleName(configure.toolTip())
            configure.setProperty("variant", "outline")
            set_button_icon(configure, "settings")
            configure.clicked.connect(lambda _checked=False, key=key: self.identity_configuration_requested.emit(key))
            row.addWidget(configure)
            self.identity_configuration_buttons[key] = configure
            form_root.addLayout(row)
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
        if self.hero_frame is None or self.form_frame is None or self.form_scroll is None:
            return
        wide = self.width() >= 840
        self.hero_frame.setVisible(wide)
        left_width = self.width() // 2 if wide else 0
        self.hero_frame.setFixedWidth(left_width)
        self.form_scroll.setFixedWidth(self.width() - left_width)
        margin = 68 if wide else 24
        self.form_frame.layout().setContentsMargins(margin, 44, margin, 28)

    def _apply_default_theme(self) -> None:
        application = QApplication.instance()
        if application is None:
            return
        engine = ThemeEngine()
        engine.apply_to(application)


def _visibility_icon(password_visible: bool) -> QIcon:
    return ui_icon("eye-off" if password_visible else "eye")
