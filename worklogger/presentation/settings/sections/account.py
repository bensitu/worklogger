"""Account settings controls."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from worklogger.infrastructure.i18n import _
from worklogger.presentation.settings.sections.actions import SectionActions
from worklogger.presentation.settings.sections.common import (
    _readonly_line_edit,
    _secondary_label,
    _section_title,
    _SettingsScrollPage,
)
from worklogger.presentation.widgets import CardFrame
from worklogger.presentation.widgets.icons import set_button_icon
from worklogger.presentation.widgets.display_name_editor import DisplayNameEditor


class AccountSection(_SettingsScrollPage):
    control_names = (
        "change_password_button",
        "current_user_id_line_edit",
        "current_user_name_line_edit",
        "current_user_role_line_edit",
        "logout_button",
        "manage_identities_button",
        "manage_users_button",
        "avatar_preview_label",
        "change_avatar_button",
        "reset_avatar_button",
        "display_name_editor",
    )

    def __init__(self, actions: SectionActions):
        super().__init__()
        page = self
        card = CardFrame(object_name="settings_content_frame")
        card.content_layout.addWidget(_section_title(_("Account")))
        form = QFormLayout()
        form.setSpacing(12)
        self.display_name_editor = DisplayNameEditor()
        self.current_user_name_line_edit = self.display_name_editor.input
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.current_user_id_line_edit = _readonly_line_edit("account_id_line_edit")
        self.current_user_role_line_edit = _readonly_line_edit("account_role_line_edit")
        form.addRow(_("Display name"), self.display_name_editor)
        form.addRow(_("Login ID"), self.current_user_id_line_edit)
        form.addRow(_("Role"), self.current_user_role_line_edit)
        avatar_row = QWidget()
        avatar_row.setObjectName("account_avatar_row_widget")
        avatar_layout = QHBoxLayout(avatar_row)
        avatar_layout.setContentsMargins(0, 0, 0, 0)
        self.avatar_preview_label = QLabel()
        self.avatar_preview_label.setObjectName("account_avatar_label")
        self.avatar_preview_label.setFixedSize(72, 72)
        self.change_avatar_button = QPushButton(_("Change avatar"))
        self.change_avatar_button.setObjectName("change_avatar_button")
        set_button_icon(self.change_avatar_button, "upload")
        self.change_avatar_button.clicked.connect(actions.change_avatar_requested)
        self.reset_avatar_button = QPushButton(_("Use default avatar"))
        self.reset_avatar_button.setObjectName("reset_avatar_button")
        self.reset_avatar_button.clicked.connect(actions.reset_avatar_requested)
        avatar_layout.addWidget(self.avatar_preview_label)
        avatar_layout.addWidget(self.change_avatar_button)
        avatar_layout.addWidget(self.reset_avatar_button)
        avatar_layout.addStretch()
        form.addRow(_("Avatar"), avatar_row)
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
