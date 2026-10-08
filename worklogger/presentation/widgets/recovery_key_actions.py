"""Explicit copy and file export actions for a displayed recovery key."""

from pathlib import Path

from PySide6.QtWidgets import QApplication, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from worklogger.infrastructure.i18n import _
from worklogger.infrastructure.security.recovery_export import export_recovery_key
from worklogger.presentation.widgets.feedback import show_information
from worklogger.presentation.widgets.icons import set_button_icon


class RecoveryKeyActions(QWidget):
    def __init__(self, key_provider, parent=None):
        super().__init__(parent)
        self._key_provider = key_provider
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        warning = QLabel(_("Keep this recovery key private. The saved file is not encrypted."))
        warning.setProperty("role", "secondary")
        warning.setWordWrap(True)
        layout.addWidget(warning)
        buttons = QHBoxLayout()
        self.copy_button = QPushButton(_("Copy recovery key"))
        self.save_button = QPushButton(_("Save recovery key"))
        for button, icon in ((self.copy_button, "copy"), (self.save_button, "file-output")):
            set_button_icon(button, icon)
            button.setAutoDefault(False)
            button.setMinimumHeight(36)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self._key_provider()))
        self.save_button.clicked.connect(self._choose_destination)

    def _choose_destination(self):
        path, _filter = QFileDialog.getSaveFileName(self, _("Save recovery key"),
            "worklogger-recovery-key.txt", _("Text files (*.txt)"))
        if path:
            self.save_to(Path(path))

    def save_to(self, destination: Path):
        result = export_recovery_key(destination, self._key_provider())
        if result.ok:
            show_information(self, _("Save recovery key"), _("Recovery key saved."))
        else:
            QMessageBox.warning(self, _("Error"), _("Unable to save the recovery key. Choose another location and try again."))
        return result
