"""Explicit copy and file export actions for a displayed account credential."""

from pathlib import Path

from PySide6.QtWidgets import QApplication, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from worklogger.infrastructure.i18n import _
from worklogger.infrastructure.security.credential_export import export_credential
from worklogger.presentation.widgets.feedback import show_information
from worklogger.presentation.widgets.icons import set_button_icon


class CredentialActions(QWidget):
    def __init__(self, key_provider, parent=None, *, temporary_password=False):
        super().__init__(parent)
        self._key_provider = key_provider
        self._temporary_password = temporary_password
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.warning_label = QLabel()
        self.warning_label.setProperty("role", "secondary")
        self.warning_label.setWordWrap(True)
        layout.addWidget(self.warning_label)
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
        self.set_temporary_password(temporary_password)

    def set_temporary_password(self, temporary: bool):
        self._temporary_password = temporary
        self.copy_button.setText(_("Copy temporary password") if temporary else _("Copy recovery key"))
        self.save_button.setText(_("Save temporary password") if temporary else _("Save recovery key"))
        self.warning_label.setText(_("Keep this temporary password private. The saved file is not encrypted.") if temporary
                                   else _("Keep this recovery key private. The saved file is not encrypted."))

    def _choose_destination(self):
        path, _filter = QFileDialog.getSaveFileName(self, self.save_button.text(),
            "worklogger-temporary-password.txt" if self._temporary_password else "worklogger-recovery-key.txt", _("Text files (*.txt)"))
        if path:
            self.save_to(Path(path))

    def save_to(self, destination: Path):
        result = export_credential(destination, self._key_provider())
        if result.ok:
            show_information(self, self.save_button.text(), _("Temporary password saved.") if self._temporary_password else _("Recovery key saved."))
        else:
            QMessageBox.warning(self, _("Error"), _("Unable to save the temporary password. Choose another location and try again.")
                                if self._temporary_password else _("Unable to save the recovery key. Choose another location and try again."))
        return result


def fit_credential_result(dialog):
    dialog.layout().activate()
    height = dialog.layout().totalHeightForWidth(dialog.width())
    dialog.resize(dialog.width(), max(300, height if height > 0 else dialog.sizeHint().height()))
