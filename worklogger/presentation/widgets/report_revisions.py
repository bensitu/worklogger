"""Version preview, source references and deliberate report recovery."""

from datetime import timezone
from PySide6.QtCore import Qt, QTimer, Signal, QSize
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QTabWidget, QTextEdit, QVBoxLayout
from shiboken6 import isValid
from worklogger.domain.shared.result import Result
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.widgets.assets import apply_window_icon
from worklogger.presentation.widgets.icons import set_button_icon
from worklogger.presentation.report_source_labels import provenance_text


class ReportRevisionsDialog(QDialog):
    restored = Signal(object)

    def __init__(self, model, state, parent=None, *, job_runner=None):
        super().__init__(parent)
        self._model, self._state, self._runner = model, state, job_runner
        self._busy = False
        self._loaded = False
        self.setWindowTitle(_("Report versions"))
        self.setWindowModality(Qt.WindowModality.WindowModal)
        apply_window_icon(self)
        self.resize(950, 620)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        types = {"daily": _("Daily Report"), "weekly": _("Weekly Report"), "monthly": _("Monthly Report")}
        self.scope_label = QLabel(_("{type} #{id} | {start} - {end}").format(type=types[state.report_type],
            id=state.report_id, start=state.period_start.isoformat(), end=state.period_end.isoformat()))
        self.scope_label.setWordWrap(True)
        root.addWidget(self.scope_label)
        body = QHBoxLayout()
        self.versions = QListWidget()
        self.versions.setObjectName("report_versions_list_view")
        self.versions.setSpacing(4)
        self.versions.setWordWrap(True)
        self.versions.setMaximumWidth(320)
        body.addWidget(self.versions, 1)
        tabs = QTabWidget()
        self.preview, self.sources = QTextEdit(), QTextEdit()
        for field in (self.preview, self.sources):
            field.setReadOnly(True)
            field.setAcceptRichText(False)
        tabs.addTab(self.preview, _("Content"))
        tabs.addTab(self.sources, _("Sources"))
        body.addWidget(tabs, 2)
        root.addLayout(body, 1)
        self.status_label = QLabel(_("The latest 50 saved versions are retained. Restoring creates a new version."))
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        footer = QHBoxLayout()
        footer.addStretch()
        self.close_button = QPushButton(_("Close"))
        self.restore_button = QPushButton(_("Restore version"))
        set_button_icon(self.restore_button, "rotate-ccw")
        self.restore_button.setEnabled(False)
        for field in (self.close_button, self.restore_button):
            field.setAutoDefault(False)
            footer.addWidget(field)
        root.addLayout(footer)
        self.versions.currentItemChanged.connect(self._preview)
        self.close_button.clicked.connect(self.reject)
        self.restore_button.clicked.connect(self._restore)
        QTimer.singleShot(0, self._load)

    def _run(self, name, operation, complete):
        self._busy = True
        self.close_button.setEnabled(False)
        self.restore_button.setEnabled(False)
        self.versions.setEnabled(False)
        def finished(result):
            if not isValid(self):
                return
            self._busy = False
            self.close_button.setEnabled(True)
            self.versions.setEnabled(True)
            complete(result)
        if self._runner is None:
            finished(operation())
        else:
            try:
                self._runner.submit(name, lambda _token: operation(), on_complete=finished)
            except Exception:
                finished(Result.failure(InfrastructureError("report_history_failed", "report_history_failed")))

    def _load(self):
        if not isValid(self) or self._loaded:
            return
        self._loaded = True
        def completed(result):
            if not result.ok:
                self.status_label.setText(display_error_message(result.error))
                return
            for version in result.value:
                stamp = version.saved_at
                if stamp is not None:
                    stamp = stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp
                text = _("Version {number}").format(number=version.revision + 1)
                text += "\n" + (stamp.astimezone().strftime("%Y-%m-%d %H:%M:%S") if stamp else _("Save time unavailable"))
                if version.revision == self._state.revision:
                    text += "\n" + _("Current saved version")
                item = QListWidgetItem(text)
                item.setSizeHint(QSize(250, 80))
                item.setData(Qt.ItemDataRole.UserRole, version)
                self.versions.addItem(item)
            if self.versions.count():
                self.versions.setCurrentRow(0)
        reader = getattr(self._model, "list_revision_headers", self._model.list_revisions)
        self._run("report_versions", lambda: reader(self._state), completed)

    def _preview(self, current, _previous=None):
        if current is None:
            self.restore_button.setEnabled(False)
            return
        version = current.data(Qt.ItemDataRole.UserRole)
        def display(result):
            if not result.ok:
                self.status_label.setText(display_error_message(result.error))
                return
            value = result.value
            self.preview.setPlainText(value.content)
            self.sources.setPlainText(provenance_text(value.provenance, reference_limit=1000))
            self.restore_button.setEnabled(not self._busy and version.revision != self._state.revision)
        if hasattr(self._model, "get_revision"):
            self._run("report_version_preview", lambda: self._model.get_revision(self._state, version.revision), display)
        else:
            display(Result.success(version))

    def _restore(self):
        current = self.versions.currentItem()
        if self._busy or current is None:
            return
        version = current.data(Qt.ItemDataRole.UserRole)
        if QMessageBox.question(self, _("Restore version"),
            _("Restore this version as the current report? Any unsaved editor content will be replaced after successful recovery."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        def completed(result):
            if result.ok:
                self.restored.emit(result.value)
                self.accept()
            else:
                self.status_label.setText(display_error_message(result.error))
                self._preview(current)
        self._run("restore_report_version", lambda: self._model.restore_revision(self._state, version.revision), completed)

    def reject(self):
        if not self._busy:
            super().reject()

    def closeEvent(self, event):
        if self._busy:
            event.ignore()
        else:
            super().closeEvent(event)
