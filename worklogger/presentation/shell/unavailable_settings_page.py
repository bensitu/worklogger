"""Unavailable settings state."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QVBoxLayout,
    QWidget,
)

from worklogger.infrastructure.i18n import _


class UnavailableSettingsPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settings_unavailable_page_widget")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        message = QLabel(_("Settings are not configured."))
        message.setObjectName("settings_unavailable_label")
        message.setProperty("role", "secondary")
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(message, 1)

    def refresh(self) -> bool:
        return False
