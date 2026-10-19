"""Non-destructive assistance for failures before the main window opens."""

import re
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from worklogger.__about__ import APP_VERSION
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.widgets.assets import apply_window_icon
from worklogger.presentation.widgets.file_location import FileLocationPanel
from worklogger.presentation.widgets.icons import set_button_icon
from worklogger.presentation.widgets.status_label import StatusLabel


class StartupErrorDialog(QDialog):
    def __init__(self, error, *, database_path, log_path, configuration_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Startup assistance"))
        apply_window_icon(self)
        self.setMinimumWidth(420)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(16)
        for text, role in (
            (_("WorkLogger could not finish starting."), "section_heading"),
            (display_error_message(error), ""),
            (_("Resolve the issue, then choose Retry. Retrying does not reset your database. Choose Exit to close WorkLogger."), "secondary"),
        ):
            label = QLabel(text)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            label.setProperty("role", role)
            root.addWidget(label)
        resource = error.details.get("resource", "database") if error else "database"
        if resource == "logging" or (error is not None and error.code in {"desktop_runtime_failed", "auth_state_failed"}):
            path, caption, action = log_path, _("Log file (read-only)"), _("Open log directory")
        elif resource == "configuration":
            path, caption, action = configuration_path, _("Configuration file (read-only)"), _("Open configuration directory")
        else:
            path, caption, action = database_path, _("Database file (read-only)"), _("Open data directory")
        self.location = FileLocationPanel(path, caption, action)
        root.addWidget(self.location)
        self.status_label = StatusLabel()
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        self.location.open_failed.connect(self._directory_failed)
        code = error.code if error and re.fullmatch(r"[a-z0-9_]{1,100}", error.code) else "unknown"
        self._diagnostics = "\n".join((
            f"WorkLogger {APP_VERSION} ({sys.platform})", code,
            _("Database: {path}").format(path=database_path),
            _("Log: {path}").format(path=log_path),
            _("Configuration: {path}").format(path=configuration_path),
        ))
        actions = QHBoxLayout()
        self.copy_button = QPushButton(_("Copy diagnostics"))
        self.copy_button.setAutoDefault(False)
        set_button_icon(self.copy_button, "copy")
        self.copy_button.clicked.connect(self._copy_diagnostics)
        actions.addWidget(self.copy_button)
        actions.addStretch()
        self.exit_button = QPushButton(_("Exit"))
        self.exit_button.setDefault(True)
        set_button_icon(self.exit_button, "x")
        self.exit_button.clicked.connect(self.reject)
        actions.addWidget(self.exit_button)
        self.retry_button = QPushButton(_("Retry"))
        self.retry_button.setProperty("variant", "primary")
        self.retry_button.setAutoDefault(False)
        set_button_icon(self.retry_button, "rotate-ccw")
        self.retry_button.clicked.connect(self.accept)
        actions.addWidget(self.retry_button)
        root.addLayout(actions)
        self.resize(600, self.sizeHint().height())

    def _directory_failed(self):
        self.status_label.setText(_("Unable to open the directory. Use the file path shown above."))

    def _copy_diagnostics(self):
        QApplication.clipboard().setText(self._diagnostics)
        self.status_label.setText(_("Diagnostics copied. Review the file paths before sharing them with support."))
