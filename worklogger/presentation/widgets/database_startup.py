"""Guided recovery actions when the desktop database cannot be opened."""

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QLabel, QLineEdit, QMessageBox, QProgressBar,
    QPushButton, QVBoxLayout,
)

from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_code, display_error_message
from worklogger.presentation.job_runner import QtJobRunner, owned_callback
from worklogger.presentation.widgets.assets import apply_window_icon
from worklogger.presentation.widgets.icons import set_button_icon
from worklogger.presentation.widgets.status_label import StatusLabel


class DatabaseStartupDialog(QDialog):
    def __init__(self, path, error, handler, parent=None, *, job_runner=None):
        super().__init__(parent)
        self._path, self._handler = path, handler
        self._runner = job_runner or QtJobRunner(self)
        self._busy = False
        self.setObjectName("database_startup_dialog")
        self.setWindowTitle(_("Database recovery"))
        apply_window_icon(self)
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        title = QLabel(_("WorkLogger could not open the database."))
        title.setProperty("role", "section_heading")
        title.setWordWrap(True)
        layout.addWidget(title)
        reason = QLabel(display_error_message(error))
        reason.setWordWrap(True)
        layout.addWidget(reason)
        guidance = QLabel(_("Choose a compatible SQLite backup or keep the existing files and create an empty database. Your current files will be retained before replacement."))
        guidance.setWordWrap(True)
        guidance.setProperty("role", "secondary")
        layout.addWidget(guidance)
        caption = QLabel(_("Database file"))
        layout.addWidget(caption)
        self.path_input = QLineEdit(str(path))
        self.path_input.setReadOnly(True)
        self.path_input.setToolTip(str(path))
        self.path_input.setAccessibleName(caption.text())
        layout.addWidget(self.path_input)
        self.open_button = QPushButton(_("Open data directory"))
        self.restore_button = QPushButton(_("Restore from database backup"))
        self.new_button = QPushButton(_("Keep existing database and create new"))
        self.exit_button = QPushButton(_("Exit"))
        self._buttons = (self.open_button, self.restore_button, self.new_button, self.exit_button)
        for button, icon in zip(self._buttons, ("folder-open", "rotate-ccw", "database", "x")):
            button.setProperty("variant", "outline")
            button.setAutoDefault(False)
            set_button_icon(button, icon)
            layout.addWidget(button)
        self.exit_button.setDefault(True)
        self.new_button.setEnabled(handler.allow_new_database)
        if not handler.allow_new_database:
            self.new_button.setToolTip(display_error_code("self_registration_disabled"))
            guidance.setText(_("Registration is disabled for this installation. Restore a compatible database backup or contact your administrator."))
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.setAccessibleName(_("Loading..."))
        layout.addWidget(self.progress)
        self.progress.hide()
        self.status_label = StatusLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.open_button.clicked.connect(self._open_directory)
        self.restore_button.clicked.connect(self._restore)
        self.new_button.clicked.connect(self._create)
        self.exit_button.clicked.connect(self.reject)
        self.resize(640, self.sizeHint().height())

    def _open_directory(self):
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._path.parent))):
            self.status_label.setText(_("Unable to open the data directory. Use the database path shown above."))

    def _restore(self):
        filename, _filter = QFileDialog.getOpenFileName(self, _("Restore from database backup"), str(self._path.parent),
                                                     _("SQLite database (*.db *.sqlite *.sqlite3);;All files (*)"))
        if not filename:
            return
        if self._confirm(_("The selected backup will replace the active database. Existing database files will be retained. Sign in with an account from the backup after recovery. Continue?")):
            self._run(Path(filename))

    def _create(self):
        if self._handler.allow_new_database and self._confirm(_("Create an empty database and set up a new account? Existing database files will be retained; records will not be imported automatically.")):
            self._run(None)

    def _confirm(self, message):
        return QMessageBox.question(self, _("Database recovery"), message,
                                    QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
                                    QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Ok

    def _set_busy(self, busy):
        self._busy = busy
        for button in self._buttons:
            button.setEnabled(not busy)
        self.new_button.setEnabled(not busy and self._handler.allow_new_database)
        self.progress.setVisible(busy)

    def _run(self, backup):
        if self._busy:
            return
        self.status_label.setText(_("Preparing the database. Please wait..."))
        self._set_busy(True)

        def complete(result):
            self._set_busy(False)
            if not result.ok or result.value is None:
                self.status_label.setText(display_error_message(result.error))
                return
            QMessageBox.information(self, _("Database recovery"),
                _("The database is ready. Original files are kept in:\n{path}\n\nContinue to account setup or sign-in.").format(path=result.value))
            self.accept()

        try:
            self._runner.submit("recover_startup_database", lambda _token: self._handler.handle(backup),
                                on_complete=owned_callback(self, complete))
        except Exception:
            complete(Result.failure(InfrastructureError("startup_recovery_failed", "startup_recovery_failed")))

    def reject(self):
        if not self._busy:
            super().reject()

    def closeEvent(self, event):
        if self._busy:
            event.ignore()
        else:
            super().closeEvent(event)
