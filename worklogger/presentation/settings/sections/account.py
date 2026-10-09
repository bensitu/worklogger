"""Account settings controls."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QPushButton,
)

from worklogger.infrastructure.i18n import _
from worklogger.presentation.settings.sections.actions import SectionActions
from worklogger.presentation.settings.sections.common import (
    _readonly_line_edit,
    _secondary_label,
    _SettingsScrollPage,
)
from worklogger.presentation.widgets import CardFrame
from worklogger.presentation.widgets.icons import set_button_icon


class AccountSection(_SettingsScrollPage):
    control_names = (
        "change_password_button",
        "current_user_id_line_edit",
        "current_user_name_line_edit",
        "current_user_role_line_edit",
        "logout_button",
        "manage_identities_button",
        "manage_users_button",
    )

    def __init__(self, actions: SectionActions):
        super().__init__()
        page = self
        card = CardFrame(object_name="settings_content_frame")
        form = QFormLayout()
        form.setSpacing(12)
        self.current_user_name_line_edit = _readonly_line_edit("account_name_line_edit")
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.current_user_id_line_edit = _readonly_line_edit("account_id_line_edit")
        self.current_user_role_line_edit = _readonly_line_edit("account_role_line_edit")
        form.addRow(_("Current user"), self.current_user_name_line_edit)
        form.addRow(_("Current ID"), self.current_user_id_line_edit)
        form.addRow(_("Role"), self.current_user_role_line_edit)
        card.content_layout.addLayout(form)
        card.content_layout.addWidget(
            _secondary_label(_("Changing password will reset the recovery key."))
        )
        self.change_password_button = QPushButton(_("Change password"))
        self.change_password_button.setObjectName("change_password_button")
        self.change_password_button.setProperty("variant", "outline")
        self.change_password_button.clicked.connect(actions.change_password_requested)
        self.manage_users_button = QPushButton(_("Manage users"))
        self.manage_users_button.setObjectName("manage_users_button")
        self.manage_users_button.setProperty("variant", "outline")
        self.manage_users_button.clicked.connect(actions.manage_users_requested)
        self.logout_button = QPushButton(_("Log Out"))
        self.logout_button.setObjectName("settings_logout_button")
        self.logout_button.setProperty("variant", "outline")
        self.logout_button.clicked.connect(actions.confirm_logout)
        self.manage_identities_button = QPushButton(_("Linked identities"))
        self.manage_identities_button.setObjectName("manage_identities_button")
        self.manage_identities_button.setProperty("variant", "outline")
        self.manage_identities_button.clicked.connect(
            actions.manage_identities_requested
        )
        for button in (
            self.change_password_button,
            self.manage_users_button,
            self.logout_button,
            self.manage_identities_button,
        ):
            card.content_layout.addWidget(button)
        for button, icon in (
            (self.change_password_button, "lock-keyhole"),
            (self.manage_users_button, "users"),
            (self.logout_button, "log-out"),
            (self.manage_identities_button, "link"),
        ):
            set_button_icon(button, icon, accent=True)
        page.layout().addWidget(card)
        page.layout().addStretch(1)
