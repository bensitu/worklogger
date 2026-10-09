"""Ai settings controls."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
)

from worklogger.config.constants import (
    AI_ASSIST_ENABLED_SETTING_KEY,
    AI_PRIVACY_INCLUDE_CALENDAR_SETTING_KEY,
    AI_PRIVACY_INCLUDE_NOTES_SETTING_KEY,
    AI_PRIVACY_INCLUDE_QUICK_LOGS_SETTING_KEY,
    EXTERNAL_MODEL_BASE_URL_SETTING_KEY,
    EXTERNAL_MODEL_NAME_SETTING_KEY,
    LOCAL_MODEL_ENABLED_SETTING_KEY,
)
from worklogger.infrastructure.i18n import _
from worklogger.presentation.settings.sections.actions import SectionActions
from worklogger.presentation.settings.sections.common import (
    _add_action_buttons,
    _secondary_label,
    _section_title,
    _SettingsScrollPage,
    _switch_line,
)
from worklogger.presentation.widgets import CardFrame, SwitchButton
from worklogger.presentation.widgets.icons import set_button_icon


class AISection(_SettingsScrollPage):
    control_names = (
        "ai_calendar_switch",
        "ai_enabled_switch",
        "ai_notes_switch",
        "ai_quick_logs_switch",
        "external_api_key_line_edit",
        "external_base_url_line_edit",
        "external_model_line_edit",
        "external_model_status_label",
        "external_runtime_status_label",
        "local_model_enabled_switch",
        "local_model_status_label",
        "local_runtime_status_label",
        "manage_local_models_button",
        "test_external_model_button",
    )

    def __init__(self, actions: SectionActions):
        super().__init__()
        page = self

        external = CardFrame(object_name="settings_content_frame")
        external.content_layout.addWidget(_section_title(_("External Model")))
        self.external_runtime_status_label = _secondary_label("")
        external.content_layout.addWidget(self.external_runtime_status_label)
        form = QFormLayout()
        form.setSpacing(12)
        self.external_api_key_line_edit = QLineEdit()
        self.external_api_key_line_edit.setObjectName("external_api_key_line_edit")
        self.external_api_key_line_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.external_api_key_line_edit.setEnabled(False)
        self.external_api_key_line_edit.setToolTip(
            _("External model testing is not configured.")
        )
        self.external_api_key_line_edit.setPlaceholderText("")
        self.external_api_key_line_edit.editingFinished.connect(
            actions.save_external_api_key
        )
        form.addRow(_("API Key"), self.external_api_key_line_edit)
        self.external_base_url_line_edit = QLineEdit()
        self.external_base_url_line_edit.setObjectName("external_base_url_line_edit")
        self.external_base_url_line_edit.setPlaceholderText(
            "https://api.example.com/v1"
        )
        self.external_base_url_line_edit.editingFinished.connect(
            lambda: actions.set_text(
                EXTERNAL_MODEL_BASE_URL_SETTING_KEY,
                self.external_base_url_line_edit.text(),
            )
        )
        form.addRow(_("API Base URL"), self.external_base_url_line_edit)
        self.external_model_line_edit = QLineEdit()
        self.external_model_line_edit.setObjectName("external_model_line_edit")
        self.external_model_line_edit.setPlaceholderText(_("Model identifier"))
        self.external_model_line_edit.editingFinished.connect(
            lambda: actions.set_text(
                EXTERNAL_MODEL_NAME_SETTING_KEY, self.external_model_line_edit.text()
            )
        )
        form.addRow(_("Model"), self.external_model_line_edit)
        external.content_layout.addLayout(form)
        self.test_external_model_button = QPushButton(_("Test"))
        self.test_external_model_button.setObjectName("test_external_model_button")
        self.test_external_model_button.setEnabled(False)
        self.test_external_model_button.setToolTip(
            _("External model testing is not configured.")
        )
        self.external_model_status_label = _secondary_label(
            _("External model testing is not configured.")
        )
        self.external_model_status_label.setObjectName("external_model_status_label")
        external.content_layout.addWidget(
            self.test_external_model_button, 0, Qt.AlignmentFlag.AlignLeft
        )
        external.content_layout.addWidget(self.external_model_status_label)
        page.layout().addWidget(external)

        local = CardFrame(object_name="settings_content_frame")
        local.content_layout.addWidget(_section_title(_("Local Model")))
        local_row = QHBoxLayout()
        local_row.setContentsMargins(0, 0, 0, 0)
        local_row.addWidget(QLabel(_("Enable local model")))
        local_row.addStretch(1)
        self.local_model_enabled_switch = SwitchButton()
        self.local_model_enabled_switch.toggled.connect(
            lambda enabled: actions.set_bool(LOCAL_MODEL_ENABLED_SETTING_KEY, enabled)
        )
        local_row.addWidget(self.local_model_enabled_switch)
        local.content_layout.addLayout(local_row)
        local.content_layout.addWidget(
            _secondary_label(
                _("Local text processing does not send content to an external service.")
            )
        )
        self.local_model_status_label = QLabel(
            _("Manage downloaded and imported GGUF models.")
        )
        self.local_model_status_label.setWordWrap(True)
        self.local_model_status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.local_model_status_label.setObjectName("local_model_status_label")
        self.local_model_status_label.setProperty("role", "secondary")
        local.content_layout.addWidget(self.local_model_status_label)
        self.local_runtime_status_label = _secondary_label("")
        local.content_layout.addWidget(self.local_runtime_status_label)
        self.manage_local_models_button = QPushButton(_("Manage models"))
        self.manage_local_models_button.setObjectName("manage_local_models_button")
        self.manage_local_models_button.clicked.connect(
            actions.manage_local_models_requested
        )
        self.manage_local_models_button.setProperty("variant", "outline")
        set_button_icon(self.manage_local_models_button, "settings", accent=True)
        _add_action_buttons(local, self.manage_local_models_button, columns=1)
        page.layout().addWidget(local)

        privacy = CardFrame(object_name="settings_content_frame")
        privacy.content_layout.addWidget(_section_title(_("AI Privacy")))
        self.ai_enabled_switch = SwitchButton()
        self.ai_enabled_switch.toggled.connect(
            lambda enabled: actions.set_bool(AI_ASSIST_ENABLED_SETTING_KEY, enabled)
        )
        privacy.content_layout.addWidget(
            _switch_line(_("AI Assist"), self.ai_enabled_switch)
        )
        self.ai_notes_switch = SwitchButton()
        self.ai_notes_switch.toggled.connect(
            lambda enabled: actions.set_bool(
                AI_PRIVACY_INCLUDE_NOTES_SETTING_KEY, enabled
            )
        )
        privacy.content_layout.addWidget(
            _switch_line(_("Include work content"), self.ai_notes_switch)
        )
        self.ai_calendar_switch = SwitchButton()
        self.ai_calendar_switch.toggled.connect(
            lambda enabled: actions.set_bool(
                AI_PRIVACY_INCLUDE_CALENDAR_SETTING_KEY, enabled
            )
        )
        privacy.content_layout.addWidget(
            _switch_line(_("Include calendar"), self.ai_calendar_switch)
        )
        self.ai_quick_logs_switch = SwitchButton()
        self.ai_quick_logs_switch.toggled.connect(
            lambda enabled: actions.set_bool(
                AI_PRIVACY_INCLUDE_QUICK_LOGS_SETTING_KEY, enabled
            )
        )
        privacy.content_layout.addWidget(
            _switch_line(_("Include quick logs"), self.ai_quick_logs_switch)
        )
        page.layout().addWidget(privacy)
        page.layout().addStretch(1)
