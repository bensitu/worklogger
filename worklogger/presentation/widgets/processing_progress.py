"""Compact indeterminate progress and an accessible cancellation action."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QProgressBar, QToolButton, QSizePolicy
from worklogger.infrastructure.i18n import _
from worklogger.presentation.widgets.icons import set_button_icon


class ProcessingProgress(QWidget):
    cancel_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("processing_progress_widget")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setMinimumWidth(0)
        row.addWidget(self.label, 1)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        self.bar.setFixedSize(72, 6)
        self.bar.setAccessibleName(_("Processing"))
        row.addWidget(self.bar)
        self.cancel_button = QToolButton()
        self.cancel_button.setObjectName("cancel_processing_button")
        self.cancel_button.setProperty("variant", "ghost")
        self.cancel_button.setFixedSize(32, 32)
        self.cancel_button.setAccessibleName(_("Cancel processing"))
        self.cancel_button.setToolTip(_("Cancel processing"))
        set_button_icon(self.cancel_button, "x")
        self.cancel_button.clicked.connect(self.cancel_requested)
        row.addWidget(self.cancel_button)
        self.hide()

    def start(self, message):
        self.label.setText(message)
        self.show()

    def finish(self):
        self.hide()
