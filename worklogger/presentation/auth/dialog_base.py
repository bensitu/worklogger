"""Authentication dialog completion rules and shared credential display."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from worklogger.config.constants import PASSWORD_MIN_LENGTH
from worklogger.infrastructure.i18n import _
from worklogger.presentation.theme import ThemeEngine, configure_application_style, install_bundled_fonts
from worklogger.presentation.theme.widget_style import set_style_property
from worklogger.presentation.widgets.assets import pixmap_asset
from worklogger.presentation.widgets.credential_actions import CredentialActions
from worklogger.presentation.widgets.processing_progress import ProcessingProgress
from worklogger.presentation.widgets.status_label import StatusLabel


class AuthDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        configure_application_style()
        install_bundled_fonts()
        application = QApplication.instance()
        if application is not None and not application.styleSheet():
            ThemeEngine().apply_to(application)

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
        self.recovery_key_caption.setProperty("role", "section_heading")
        self.recovery_key_label = QLabel("")
        self.recovery_key_label.setObjectName("recovery_key_label")
        self.recovery_key_label.setWordWrap(True)
        self.recovery_key_label.setMinimumWidth(0)
        self.recovery_key_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.recovery_key_label.setTextFormat(Qt.TextFormat.PlainText)
        self.recovery_key_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.recovery_actions = CredentialActions(self.recovery_key_label.text, self)
        for widget in (self.recovery_key_caption, self.recovery_key_label, self.recovery_actions):
            widget.hide()
            layout.addWidget(widget)

    def _build_credential_form(self, subtitle):
        self.setProperty("credential_form", True)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)
        header = QWidget()
        header.setObjectName("credential_header_widget")
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(12)
        self.brand_icon_label = QLabel()
        self.brand_icon_label.setFixedSize(48, 48)
        self.brand_icon_label.setPixmap(pixmap_asset("icons/worklogger.webp").scaled(
            48, 48, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        header_row.addWidget(self.brand_icon_label)
        heading = QVBoxLayout()
        heading.setSpacing(2)
        self.title_label = QLabel(_("WorkLogger"))
        self.title_label.setProperty("role", "title")
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setProperty("role", "section_heading")
        self.subtitle_label.setWordWrap(True)
        heading.addWidget(self.title_label)
        heading.addWidget(self.subtitle_label)
        header_row.addLayout(heading, 1)
        root.addWidget(header)
        self.account_label = QLabel()
        self.account_label.setTextFormat(Qt.TextFormat.PlainText)
        self.account_label.setWordWrap(True)
        self.account_label.setProperty("role", "account_identity")
        self.account_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.account_label.hide()
        root.addWidget(self.account_label)
        self.password_fields = QWidget()
        self.password_fields.setObjectName("credential_form_widget")
        form = QFormLayout(self.password_fields)
        form.setContentsMargins(0, 0, 0, 0)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setVerticalSpacing(6)
        root.addWidget(self.password_fields)
        self.status_label = StatusLabel()
        self.status_label.setObjectName("auth_status_label")
        self.feedback_stack = QStackedWidget()
        self.feedback_stack.setObjectName("credential_feedback_stack_widget")
        self.feedback_stack.setMinimumHeight(32)
        self.credential_progress = ProcessingProgress()
        self.credential_progress.cancel_button.hide()
        self.feedback_stack.addWidget(self.status_label)
        self.feedback_stack.addWidget(self.credential_progress)
        self.feedback_stack.setCurrentWidget(self.status_label)
        root.addWidget(self.feedback_stack)
        return root, form

    def _add_password_hint(self, form):
        self.password_hint_label = QLabel(_("The password must contain at least {length} characters.").format(length=PASSWORD_MIN_LENGTH))
        self.password_hint_label.setProperty("role", "caption")
        self.password_hint_label.setWordWrap(True)
        form.addRow(self.password_hint_label)

    def _set_credential_busy(self, busy, *, completed):
        self.password_fields.setEnabled(not busy and not completed)
        if busy:
            self.credential_progress.start(_("Loading..."))
            self.feedback_stack.setCurrentWidget(self.credential_progress)
        else:
            self.credential_progress.finish()
            self.feedback_stack.setCurrentWidget(self.status_label)

    def _show_credential_completion(self, message):
        self.subtitle_label.setText(message)
        set_style_property(self.subtitle_label, "role", "credential_success")
        set_style_property(self.status_label, "role", "secondary")
        self.login_button.setEnabled(False)
        self.login_button.hide()
