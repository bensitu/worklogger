"""Guided recovery actions when the desktop database cannot be opened."""

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QTextOption
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QRadioButton, QScrollArea,
    QVBoxLayout, QWidget,
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
        layout.setSpacing(16)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("database_recovery_content_widget")
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(16)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        title = QLabel(_("WorkLogger could not open the database."))
        title.setProperty("role", "section_heading")
        title.setWordWrap(True)
        body.addWidget(title)
        reason = QLabel(display_error_message(error))
        reason.setTextFormat(Qt.TextFormat.PlainText)
        reason.setWordWrap(True)
        body.addWidget(reason)

        location = QFrame()
        location.setProperty("role", "readonly_location")
        location_layout = QVBoxLayout(location)
        location_layout.setContentsMargins(12, 12, 12, 12)
        location_header = QHBoxLayout()
        caption = QLabel(_("Database file (read-only)"))
        caption.setWordWrap(True)
        location_header.addWidget(caption, 1)
        self.open_button = QPushButton(_("Open data directory"))
        self.open_button.setProperty("variant", "outline")
        self.open_button.setAutoDefault(False)
        set_button_icon(self.open_button, "folder-open")
        location_header.addWidget(self.open_button)
        location_layout.addLayout(location_header)
        self.path_view = QPlainTextEdit(str(path))
        self.path_view.setReadOnly(True)
        self.path_view.setWordWrapMode(QTextOption.WrapMode.WrapAnywhere)
        self.path_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.path_view.setFixedHeight(self.path_view.fontMetrics().lineSpacing() * 3 + 8)
        self.path_view.setToolTip(str(path))
        self.path_view.setAccessibleName(caption.text())
        self.path_view.setProperty("role", "readonly_location_path")
        location_layout.addWidget(self.path_view)
        body.addWidget(location)

        choices = QVBoxLayout()
        choices.setSpacing(12)
        heading = QLabel(_("Choose one action"))
        heading.setProperty("role", "section_heading")
        heading.setWordWrap(True)
        choices.addWidget(heading)
        self.choice_group = QButtonGroup(self)
        self.restore_choice = QRadioButton(_("Restore from database backup"))
        self.new_choice = QRadioButton(_("Keep files and create a new database"))
        self.exit_choice = QRadioButton(_("Exit without making changes"))
        self._choices = (self.restore_choice, self.new_choice, self.exit_choice)
        descriptions = (
            _("Choose a local SQLite backup (.db, .sqlite or .sqlite3), not a CSV or personal cloud archive. WorkLogger checks a copy before replacement, keeps the current files, then opens sign-in for an account from the backup."),
            _("Keep the current database and its journal files in a separate recovery folder, then start with an empty database and create a new account. Existing records are not imported."),
            _("Close WorkLogger without changing any files. Use this if you need help from your administrator or a compatible version to access the existing database."),
        )
        for choice, description in zip(self._choices, descriptions):
            self.choice_group.addButton(choice)
            choice.setObjectName("database_recovery_choice_button")
            choice.setAccessibleDescription(description)
            choices.addWidget(choice)
            details = QLabel(description)
            details.setWordWrap(True)
            details.setProperty("role", "secondary")
            details.setIndent(24)
            choices.addWidget(details)
        self.exit_choice.setChecked(True)
        self.new_choice.setEnabled(handler.allow_new_database)
        if not handler.allow_new_database:
            self.new_choice.setToolTip(display_error_code("self_registration_disabled"))
            policy = QLabel(_("Registration is disabled for this installation. Restore a compatible database backup or contact your administrator."))
            policy.setWordWrap(True)
            choices.addWidget(policy)
        body.addLayout(choices)
        body.addStretch()
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
        actions = QHBoxLayout()
        actions.addStretch()
        self.action_button = QPushButton()
        self.action_button.setProperty("variant", "primary")
        self.action_button.setDefault(True)
        actions.addWidget(self.action_button)
        layout.addLayout(actions)
        self._buttons = (self.open_button, self.action_button)
        self.open_button.clicked.connect(self._open_directory)
        self.choice_group.buttonToggled.connect(self._update_action)
        self.action_button.clicked.connect(self._execute_action)
        self._update_action()
        height = min(620, self.screen().availableGeometry().height() - 80)
        self.resize(640, height)

    def _update_action(self):
        if self.restore_choice.isChecked():
            text, icon = _("Choose backup..."), "folder-open"
        elif self.new_choice.isChecked():
            text, icon = _("Create new database..."), "database"
        else:
            text, icon = _("Exit"), "x"
        self.action_button.setText(text)
        set_button_icon(self.action_button, icon)

    def _execute_action(self):
        if self._busy:
            return
        if self.restore_choice.isChecked():
            self._restore()
        elif self.new_choice.isChecked():
            self._create()
        else:
            self.reject()

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
        for choice in self._choices:
            choice.setEnabled(not busy)
        self.new_choice.setEnabled(not busy and self._handler.allow_new_database)
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
