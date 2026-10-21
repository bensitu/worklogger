"""Explicit confirmation before interrupting unfinished background work."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QVBoxLayout

from worklogger.infrastructure.i18n import _
from worklogger.presentation.widgets.assets import apply_window_icon
from worklogger.presentation.widgets.icons import set_button_icon


class BackgroundTaskShutdownDialog(QDialog):
    force_quit_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle(_("Exit application"))
        self.setObjectName("background_task_shutdown_dialog")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        apply_window_icon(self)
        root = QVBoxLayout(self)
        self.status_label = QLabel(_("Stopping background tasks..."))
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        progress = QProgressBar()
        progress.setRange(0, 0)
        root.addWidget(progress)
        row = QHBoxLayout()
        row.addStretch()
        self.force_button = QPushButton(_("Force quit"))
        self.force_button.setProperty("variant", "danger")
        self.force_button.setAutoDefault(False)
        set_button_icon(self.force_button, "x")
        self.force_button.setEnabled(False)
        self.force_button.clicked.connect(self._confirm_force_quit)
        row.addWidget(self.force_button)
        root.addLayout(row)
        self.resize(460, 160)

    def allow_force_quit(self):
        if not self.force_button.isEnabled():
            self.status_label.setText(_("Background tasks are taking longer than expected. You can keep waiting or confirm a forced exit."))
            self.force_button.setEnabled(True)

    def _confirm_force_quit(self):
        confirmation = QMessageBox(QMessageBox.Icon.Warning, _("Force quit"),
            _("Force quitting may interrupt file operations. Keep database, journal, and recovery files if recovery is needed."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
        confirmation.setTextFormat(Qt.TextFormat.PlainText)
        confirmation.button(QMessageBox.StandardButton.Yes).setText(_("Force quit"))
        confirmation.button(QMessageBox.StandardButton.No).setText(_("Keep waiting"))
        confirmation.setDefaultButton(QMessageBox.StandardButton.No)
        try:
            if confirmation.exec() == QMessageBox.StandardButton.Yes:
                self.force_quit_requested.emit()
        finally:
            confirmation.deleteLater()

    def reject(self):
        pass

    def closeEvent(self, event):
        event.ignore()
