"""Explicit, atomic assignment of project context to selected records."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QListWidget, QMessageBox, QPushButton, QVBoxLayout
from shiboken6 import isValid
from worklogger.domain.shared.result import Result
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.widgets.assets import apply_window_icon
from worklogger.presentation.widgets.icons import set_button_icon
from worklogger.presentation.widgets.work_context_picker import WorkContextPicker


class BatchContextDialog(QDialog):
    applied = Signal(object)

    def __init__(self, model, entries, projects, items, parent=None, *, job_runner=None):
        super().__init__(parent)
        self._model, self._entries, self._runner = model, entries, job_runner
        self._busy = False
        self.setWindowTitle(_("Assign project and work item"))
        self.setWindowModality(Qt.WindowModality.WindowModal)
        apply_window_icon(self)
        self.resize(680, 480)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        self.summary_label = QLabel(_("Selected records: {count} | Existing associations: {existing}").format(
            count=len(entries), existing=sum(bool(entry.context.label) for entry in entries)))
        self.summary_label.setWordWrap(True)
        root.addWidget(self.summary_label)
        self.picker = WorkContextPicker()
        self.picker.set_inventory(projects, items)
        root.addWidget(self.picker)
        self.records_list = QListWidget()
        self.records_list.addItems([f"{entry.day.isoformat()} {entry.start_time or ''} - {entry.end_time or ''} | "
            + (entry.context.label or _("Unclassified")) for entry in entries])
        root.addWidget(self.records_list, 1)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        footer = QHBoxLayout()
        footer.addStretch()
        self.close_button, self.apply_button = QPushButton(_("Cancel")), QPushButton(_("Apply"))
        set_button_icon(self.apply_button, "check")
        self.apply_button.setProperty("variant", "primary")
        for button in (self.close_button, self.apply_button):
            button.setAutoDefault(False)
            footer.addWidget(button)
        root.addLayout(footer)
        self.close_button.clicked.connect(self.reject)
        self.apply_button.clicked.connect(self._apply)

    def _apply(self):
        if self._busy:
            return
        context = self.picker.context()
        if QMessageBox.question(self, _("Assign project and work item"),
            _("Assign {context} to {count} selected records? Existing associations will be replaced; recorded times, types and content will not change.").format(
                context=context.label or _("Unclassified"), count=len(self._entries)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self._busy = True
        for field in (self.close_button, self.apply_button, self.picker):
            field.setEnabled(False)
        def completed(result):
            if not isValid(self):
                return
            self._busy = False
            for field in (self.close_button, self.apply_button, self.picker):
                field.setEnabled(True)
            if result.ok:
                self.applied.emit(result.value)
                self.accept()
            else:
                self.status_label.setText(display_error_message(result.error))
        operation = lambda: self._model.associate(self._entries, context)
        if self._runner is None:
            completed(operation())
        else:
            try:
                self._runner.submit("associate_records", lambda _token: operation(), on_complete=completed)
            except Exception:
                completed(Result.failure(InfrastructureError("record_change_failed", "record_change_failed")))

    def reject(self):
        if not self._busy:
            super().reject()

    def closeEvent(self, event):
        if self._busy:
            event.ignore()
        else:
            super().closeEvent(event)
