"""Network settings controls."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
)

from worklogger.config.constants import (
    NETWORK_PROXY_ADDRESS_SETTING_KEY,
    NETWORK_PROXY_DOMAIN_SETTING_KEY,
    NETWORK_PROXY_ENABLED_SETTING_KEY,
    NETWORK_PROXY_PASSWORD_SETTING_KEY,
    NETWORK_PROXY_PORT_SETTING_KEY,
    NETWORK_PROXY_USERNAME_SETTING_KEY,
)
from worklogger.infrastructure.i18n import _
from worklogger.presentation.settings.sections.actions import SectionActions
from worklogger.presentation.settings.sections.common import (
    _connect_text,
    _secondary_label,
    _section_title,
    _action_card,
    _settings_form,
    _switch_line,
    _text_line_edit,
)
from worklogger.presentation.widgets import SwitchButton
from worklogger.presentation.settings.sections.layouts import SettingsFieldGroup, SettingsScrollPage
from worklogger.presentation.widgets.icons import ui_icon


class NetworkSection(SettingsScrollPage):
    control_names = (
        "proxy_address_line_edit",
        "proxy_credentials_status_label",
        "proxy_domain_line_edit",
        "proxy_enabled_switch",
        "proxy_password_line_edit",
        "proxy_password_visibility_action",
        "proxy_port_line_edit",
        "proxy_runtime_status_label",
        "proxy_username_line_edit",
    )

    def __init__(self, actions: SectionActions):
        super().__init__()
        page = self
        card = _action_card(_("Web proxy"))
        self.proxy_enabled_switch = SwitchButton()
        self.proxy_enabled_switch.toggled.connect(
            lambda enabled: actions.set_bool(NETWORK_PROXY_ENABLED_SETTING_KEY, enabled)
        )
        card.content_layout.addWidget(
            _switch_line(
                _("Use a web proxy for this application."), self.proxy_enabled_switch
            )
        )
        self.proxy_runtime_status_label = _secondary_label("")
        card.content_layout.addWidget(self.proxy_runtime_status_label)

        self.proxy_address_line_edit = _text_line_edit("proxy_address_line_edit")
        self.proxy_port_line_edit = _text_line_edit("proxy_port_line_edit")
        self.proxy_username_line_edit = _text_line_edit("proxy_username_line_edit")
        self.proxy_password_line_edit = _text_line_edit("proxy_password_line_edit")
        self.proxy_password_line_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.proxy_password_visibility_action = self.proxy_password_line_edit.addAction(
            ui_icon("eye"),
            QLineEdit.ActionPosition.TrailingPosition,
        )
        self.proxy_password_visibility_action.setToolTip(_("Show password"))
        self.proxy_password_visibility_action.triggered.connect(
            actions.toggle_proxy_password
        )
        self.proxy_domain_line_edit = _text_line_edit("proxy_domain_line_edit")
        _connect_text(
            self.proxy_address_line_edit,
            lambda: actions.set_text(
                NETWORK_PROXY_ADDRESS_SETTING_KEY, self.proxy_address_line_edit.text()
            ),
        )
        _connect_text(
            self.proxy_port_line_edit,
            lambda: actions.set_text(
                NETWORK_PROXY_PORT_SETTING_KEY, self.proxy_port_line_edit.text()
            ),
        )
        _connect_text(
            self.proxy_username_line_edit,
            lambda: actions.set_text(
                NETWORK_PROXY_USERNAME_SETTING_KEY, self.proxy_username_line_edit.text()
            ),
        )
        _connect_text(
            self.proxy_password_line_edit,
            lambda: actions.set_text(
                NETWORK_PROXY_PASSWORD_SETTING_KEY, self.proxy_password_line_edit.text()
            ),
        )
        _connect_text(
            self.proxy_domain_line_edit,
            lambda: actions.set_text(
                NETWORK_PROXY_DOMAIN_SETTING_KEY, self.proxy_domain_line_edit.text()
            ),
        )
        card.content_layout.addWidget(SettingsFieldGroup([
            ("address", QLabel(_("Address")), self.proxy_address_line_edit),
            ("port", QLabel(_("Port")), self.proxy_port_line_edit),
        ], weights={"address": 3, "port": 1}))
        card.content_layout.addWidget(_section_title(_("Authentication information (optional)")))
        form = _settings_form()
        form.addRow(_("Username"), self.proxy_username_line_edit)
        form.addRow(_("Password"), self.proxy_password_line_edit)
        form.addRow(_("Domain"), self.proxy_domain_line_edit)
        card.content_layout.addLayout(form)
        self.proxy_credentials_status_label = _secondary_label("")
        self.proxy_credentials_status_label.setObjectName(
            "proxy_credentials_status_label"
        )
        card.content_layout.addWidget(self.proxy_credentials_status_label)
        page.layout().addWidget(card)
        page.layout().addStretch(1)
