"""Modal wrapper around the shared settings page."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from worklogger.infrastructure.i18n import _
from worklogger.presentation.settings.page import SettingsPage
from worklogger.presentation.viewmodels import SettingsViewModel
from worklogger.presentation.widgets.assets import apply_window_icon


class SettingsDialog(QDialog):
    def __init__(self, view_model: SettingsViewModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settings_dialog")
        self.setWindowTitle(_("Settings"))
        self.resize(880, 580)
        apply_window_icon(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 12)
        self.page = SettingsPage(view_model, self)
        layout.addWidget(self.page, 1)
        self.close_button = QPushButton(_("Close"))
        self.close_button.setAutoDefault(False)
        self.close_button.setProperty("variant", "outline")
        self.close_button.clicked.connect(self.accept)
        footer = QHBoxLayout()
        footer.setContentsMargins(24, 0, 24, 0)
        footer.addStretch()
        footer.addWidget(self.close_button)
        layout.addLayout(footer)

    def __getattr__(self, name: str):
        page = self.__dict__.get("page")
        if page is not None:
            return getattr(page, name)
        raise AttributeError(name)

    def accept(self) -> None:
        if self.page.confirm_profile_leave():
            super().accept()

    def reject(self) -> None:
        if self.page.confirm_profile_leave():
            super().reject()

    def closeEvent(self, event) -> None:
        if not self.page.confirm_profile_leave():
            event.ignore()
        else:
            super().closeEvent(event)
