"""About settings controls."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from worklogger.__about__ import APP_AUTHOR, APP_NAME, APP_VERSION, GITHUB_URL
from worklogger.infrastructure.i18n import _
from worklogger.presentation.settings.sections.actions import SectionActions
from worklogger.presentation.settings.sections.common import (
    _secondary_label,
    _separator,
    _section_title,
    _SettingsScrollPage,
)
from worklogger.presentation.widgets.assets import pixmap_asset
from worklogger.presentation.widgets.icons import set_button_icon


class AboutSection(_SettingsScrollPage):
    control_names = (
        "about_author_label",
        "about_license_label",
        "about_name_label",
        "about_url_label",
        "about_version_label",
        "check_updates_button",
        "update_status_label",
    )

    def __init__(self, actions: SectionActions):
        super().__init__()
        page = self
        card = QWidget()
        card.setObjectName("settings_about_widget")
        card.content_layout = QVBoxLayout(card)
        card.content_layout.setContentsMargins(18, 20, 18, 20)
        card.content_layout.setSpacing(16)
        card.content_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        card.content_layout.addWidget(_section_title(_("About")), 0, Qt.AlignmentFlag.AlignLeft)
        icon = QLabel("")
        icon.setObjectName("about_icon_label")
        pixmap = pixmap_asset("icons/worklogger.webp")
        if not pixmap.isNull():
            icon.setPixmap(
                pixmap.scaled(
                    120,
                    120,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.content_layout.addWidget(icon)
        self.about_name_label = QLabel(APP_NAME)
        self.about_name_label.setObjectName("about_name_label")
        self.about_name_label.setProperty("role", "title")
        self.about_name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.about_version_label = QLabel(
            _("Version {version}").format(version=APP_VERSION)
        )
        self.about_version_label.setObjectName("about_version_label")
        self.about_version_label.setProperty("role", "secondary")
        self.about_version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_brief = QLabel(
            _("A privacy-first desktop work tracker with AI-powered reporting.")
        )
        about_brief.setObjectName("about_brief_label")
        about_brief.setProperty("role", "secondary")
        about_brief.setWordWrap(True)
        about_brief.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.content_layout.addWidget(self.about_name_label)
        card.content_layout.addWidget(self.about_version_label)
        card.content_layout.addWidget(about_brief)
        card.content_layout.addWidget(_separator())
        details = QGridLayout()
        details.setHorizontalSpacing(24)
        details.setVerticalSpacing(12)
        details.setColumnStretch(1, 1)
        self.about_author_label = QLabel(APP_AUTHOR)
        self.about_author_label.setObjectName("about_author_label")
        self.about_license_label = QLabel(_("GNU GPLv3"))
        self.about_license_label.setObjectName("about_license_label")
        self.about_url_label = QLabel(f'<a href="{GITHUB_URL}">{GITHUB_URL}</a>')
        self.about_url_label.setOpenExternalLinks(True)
        self.about_url_label.setWordWrap(True)
        self.about_url_label.setObjectName("about_url_label")
        for row, (label, widget) in enumerate(
            (
                (_("Author"), self.about_author_label),
                (_("License"), self.about_license_label),
                (_("GitHub"), self.about_url_label),
            )
        ):
            details.addWidget(QLabel(label), row, 0)
            details.addWidget(widget, row, 1)
        card.content_layout.addLayout(details)
        card.content_layout.addWidget(_separator())
        self.check_updates_button = QPushButton(_("Check for updates"))
        self.check_updates_button.setObjectName("check_updates_button")
        self.check_updates_button.setProperty("variant", "outline")
        self.check_updates_button.clicked.connect(actions.update_check_requested)
        set_button_icon(self.check_updates_button, "refresh-cw", accent=True)
        card.content_layout.addWidget(
            self.check_updates_button, 0, Qt.AlignmentFlag.AlignHCenter
        )
        self.update_status_label = _secondary_label("")
        self.update_status_label.setObjectName("update_status_label")
        self.update_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.update_status_label.setFixedHeight(48)
        self.update_status_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        self.update_status_label.setTextFormat(Qt.TextFormat.PlainText)
        size_policy = self.update_status_label.sizePolicy()
        size_policy.setRetainSizeWhenHidden(True)
        self.update_status_label.setSizePolicy(size_policy)
        self.update_status_label.hide()
        card.content_layout.addWidget(self.update_status_label)
        page.layout().addStretch(1)
        page.layout().addWidget(card)
        page.layout().addStretch(1)
