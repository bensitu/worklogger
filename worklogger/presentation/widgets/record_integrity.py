"""Review invalid records and preserve their original values before removal."""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.job_runner import owned_callback, shared_job_runner
from worklogger.presentation.widgets.assets import apply_window_icon
from worklogger.presentation.widgets.data_tree import configure_data_tree
from worklogger.presentation.widgets.icons import set_button_icon


class RecordIntegrityDialog(QDialog):
    records_changed = Signal()

    def __init__(self, view_model, parent=None, *, job_runner=None):
        super().__init__(parent)
        self._view_model, self._runner = view_model, job_runner or shared_job_runner()
        self._inspection, self._busy = None, False
        self.setWindowTitle(_("Check records"))
        self.setObjectName("record_integrity_dialog")
        self.resize(680, 440)
        apply_window_icon(self)
        root = QVBoxLayout(self)
        self.description = QLabel(_("Unreadable records are not skipped. Save their original values before removing them from this account."))
        self.description.setTextFormat(Qt.TextFormat.PlainText)
        self.description.setWordWrap(True)
        root.addWidget(self.description)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([_("Record ID"), _("Date")])
        self.tree.setRootIsDecorated(False)
        configure_data_tree(self.tree, (130, 260), stretch_column=1)
        root.addWidget(self.tree, 1)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        actions = QHBoxLayout()
        self.refresh_button = QPushButton(_("Refresh"))
        set_button_icon(self.refresh_button, "refresh-cw")
        self.refresh_button.clicked.connect(self.refresh)
        self.recover_button = QPushButton(_("Save a copy and remove invalid records"))
        self.recover_button.setProperty("variant", "danger")
        set_button_icon(self.recover_button, "save")
        self.recover_button.clicked.connect(self.recover)
        self.close_button = QPushButton(_("Close"))
        set_button_icon(self.close_button, "x")
        for button in (self.refresh_button, self.recover_button, self.close_button):
            button.setProperty("dialog_action", True)
        self.close_button.setDefault(True)
        self.close_button.clicked.connect(self.reject)
        actions.addWidget(self.refresh_button)
        actions.addStretch()
        actions.addWidget(self.recover_button)
        actions.addWidget(self.close_button)
        root.addLayout(actions)
        for button in (self.refresh_button, self.recover_button):
            button.setAutoDefault(False)
        self.refresh()

    def _set_busy(self, busy):
        self._busy = busy
        self.refresh_button.setEnabled(not busy)
        self.close_button.setEnabled(not busy)
        self.recover_button.setEnabled(not busy and self._inspection is not None and bool(self._inspection.records))

    def _run(self, operation, completed):
        if self._busy:
            return
        self._set_busy(True)
        self.status.setText(_("Please wait for the current operation."))
        def complete(result):
            self._set_busy(False)
            if result.ok:
                completed(result.value)
            else:
                self.status.setText(display_error_message(result.error))
        try:
            self._runner.submit("record_integrity", lambda _token: operation(), on_complete=owned_callback(self, complete))
        except Exception:
            complete(Result.failure(InfrastructureError("record_check_failed", "record_check_failed")))

    def refresh(self):
        self._run(self._view_model.check_records, self._show_inspection)

    def _show_inspection(self, inspection):
        self._inspection = inspection
        self.tree.clear()
        for record in inspection.records:
            self.tree.addTopLevelItem(QTreeWidgetItem([str(record.record_id), record.stored_date]))
        self.status.setText(_("Invalid records: {count}").format(count=len(inspection.records)))
        self._set_busy(False)

    def recover(self):
        if self._busy or self._inspection is None or not self._inspection.records:
            return
        confirmation = QMessageBox(QMessageBox.Icon.Warning, _("Check records"),
            _("Remove these invalid records only after saving a private recovery copy? Other records and accounts will not change."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
        confirmation.setTextFormat(Qt.TextFormat.PlainText)
        confirmation.setDefaultButton(QMessageBox.StandardButton.No)
        try:
            if confirmation.exec() != QMessageBox.StandardButton.Yes:
                return
        finally:
            confirmation.deleteLater()
        path, _filter = QFileDialog.getSaveFileName(self, _("Save recovery copy"), "invalid-records.json", "JSON (*.json)")
        if not path:
            return
        inspection = self._inspection
        self._run(lambda: self._view_model.archive_invalid_records(inspection, Path(path)), self._recovered)

    def _recovered(self, count):
        self._inspection = None
        self.tree.clear()
        self._set_busy(False)
        self.status.setText(_("Recovery copy saved. Invalid records removed: {count}").format(count=count))
        self.records_changed.emit()

    def reject(self):
        if not self._busy:
            super().reject()

    def closeEvent(self, event):
        if self._busy:
            event.ignore()
        else:
            super().closeEvent(event)
