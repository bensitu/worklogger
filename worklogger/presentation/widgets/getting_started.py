"""Nonmodal guidance for creating a first time record."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from worklogger.infrastructure.i18n import _
from worklogger.presentation.widgets.icons import set_button_icon


class GettingStartedPanel(QFrame):
    record_requested = Signal()
    dismiss_requested = Signal()
    guide_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("getting_started_panel")
        self.setProperty("onboarding_surface", True)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        title = QLabel(_("Start with your first record"))
        title.setProperty("role", "section_heading")
        title.setWordWrap(True)
        root.addWidget(title)
        description = QLabel(_(
            "Enter start and end times for completed work, or use Auto Record to time work in progress. "
            "Keep details in Notes and use Reports when you need a summary."))
        description.setWordWrap(True)
        root.addWidget(description)
        actions = QHBoxLayout()
        self.record_button = QPushButton(_("Record a time period"))
        self.record_button.setProperty("variant", "primary")
        self.dismiss_button = QPushButton(_("Maybe later"))
        self.guide_button = QPushButton(_("User guide"))
        for button, icon, signal in (
            (self.record_button, "plus", self.record_requested),
            (self.dismiss_button, "x", self.dismiss_requested),
            (self.guide_button, "file-text", self.guide_requested),
        ):
            set_button_icon(button, icon)
            actions.addWidget(button)
            button.clicked.connect(signal)
        actions.addStretch(1)
        root.addLayout(actions)
