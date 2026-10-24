"""Introduction to local account setup."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from worklogger.infrastructure.i18n import _
from worklogger.presentation.widgets.assets import pixmap_asset
from worklogger.presentation.widgets.icons import IconLabel, set_button_icon


class WelcomePage(QWidget):
    create_requested = Signal()
    exit_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("account_welcome_page")
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 24)
        root.setSpacing(20)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(20)
        brand = QHBoxLayout()
        brand.setSpacing(16)
        logo = QLabel()
        logo.setFixedSize(72, 72)
        logo.setPixmap(pixmap_asset("icons/worklogger.webp").scaled(
            72, 72, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        brand.addWidget(logo)
        brand.addWidget(self._label(_("Welcome to WorkLogger"), "title"), 1)
        layout.addLayout(brand)
        layout.addWidget(self._label(_(
            "Record work and breaks, keep daily notes, and prepare reports from your records.")))

        local = QFrame()
        local.setProperty("onboarding_surface", True)
        local_layout = QHBoxLayout(local)
        local_layout.setContentsMargins(16, 14, 16, 14)
        local_layout.setSpacing(12)
        local_layout.addWidget(IconLabel("shield-check"), 0, Qt.AlignmentFlag.AlignTop)
        local_layout.addWidget(self._label(_(
            "Start with your own local account. No online registration is required.")), 1)
        layout.addWidget(local)

        for icon, title, description in (
            ("user-round", _("Create account"), _("Choose a login ID and password.")),
            ("lock-keyhole", _("Keep your recovery key"), _(
                "Save the key provided after registration so you can reset a forgotten password.")),
            ("calendar-days", _("New time record"), _(
                "Enter a completed time period or start a timer for work in progress.")),
        ):
            row = QHBoxLayout()
            row.setSpacing(14)
            row.addWidget(IconLabel(icon), 0, Qt.AlignmentFlag.AlignTop)
            text = QVBoxLayout()
            text.setSpacing(4)
            text.addWidget(self._label(title, "account_identity"))
            text.addWidget(self._label(description, "secondary"))
            row.addLayout(text, 1)
            layout.addLayout(row)
        layout.addStretch(1)
        layout.addWidget(self._label(_(
            "Your records stay on this computer. AI assistance and cloud backups are optional."), "caption"))
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        self.exit_button = QPushButton(_("Exit"))
        self.create_button = QPushButton(_("Create my account"))
        self.create_button.setProperty("variant", "primary")
        for button, icon in ((self.exit_button, "x"), (self.create_button, "chevron-right")):
            button.setProperty("dialog_action", True)
            set_button_icon(button, icon)
        buttons.addWidget(self.exit_button)
        buttons.addStretch(1)
        buttons.addWidget(self.create_button)
        root.addLayout(buttons)
        self.exit_button.clicked.connect(self.exit_requested)
        self.create_button.clicked.connect(self.create_requested)

    @staticmethod
    def _label(text, role=None):
        label = QLabel(text)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        if role:
            label.setProperty("role", role)
        return label
