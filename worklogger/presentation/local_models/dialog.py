"""Local model management dialog."""

from __future__ import annotations

from pathlib import Path
from dataclasses import replace

from PySide6.QtCore import QSignalBlocker, Qt, Signal

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from worklogger.app.job_runner import JobHandle, JobRunner
from worklogger.domain.shared.errors import AppError, CancellationError, InfrastructureError
from worklogger.infrastructure.i18n import _, get_language
from worklogger.presentation.errors import display_error_code, display_error_message
from worklogger.presentation.job_runner import QtJobRunner
from worklogger.presentation.viewmodels import (
    LocalModelManagerState,
    LocalModelManagerViewModel,
)
from worklogger.presentation.widgets.assets import apply_window_icon
from worklogger.presentation.widgets.status_label import StatusLabel
from worklogger.presentation.widgets.icons import set_button_icon
from worklogger.presentation.widgets.two_line_delegate import TwoLineItemDelegate


class LocalModelsDialog(QDialog):
    download_progress = Signal(object)
    def __init__(
        self,
        view_model: LocalModelManagerViewModel,
        parent: QWidget | None = None,
        job_runner: JobRunner | None = None,
    ) -> None:
        super().__init__(parent)
        self._view_model = view_model
        self._state: LocalModelManagerState | None = None
        self._last_error: AppError | None = None
        self._job_runner = job_runner or QtJobRunner(self)
        self._pending_handle: JobHandle[object] | None = None
        self._busy = False
        self._download_active = False
        self.setObjectName("local_models_dialog")
        self.setWindowTitle(_("Local Models"))
        apply_window_icon(self)
        self._build_ui()
        self.download_progress.connect(self._show_download_progress, Qt.ConnectionType.QueuedConnection)
        self.resize(920, 560)
        self.setMinimumSize(800, 500)

    @property
    def last_error(self) -> AppError | None:
        return self._last_error

    @property
    def state(self) -> LocalModelManagerState | None:
        return self._state

    def refresh(self) -> bool:
        if self._job_runner is not None:
            return self._run_state_job("local_model_load", self._view_model.load, _("Loading models..."))
        return self._set_state_result(self._view_model.load())

    def refresh_catalog(self) -> bool:
        if self._job_runner is not None:
            return self._run_state_job(
                "local_model_refresh",
                self._view_model.refresh_catalog,
                _("Refreshing catalog..."),
            )
        return self._set_state_result(self._view_model.refresh_catalog())

    def import_model(self, source: Path | str | None = None) -> bool:
        source = source or self._choose_model_file()
        if source is None:
            self.status_label.setText(_("Import cancelled"))
            return False
        if self._job_runner is not None:
            return self._run_state_job(
                "local_model_import",
                lambda: self._view_model.import_model(source),
                _("Importing model..."),
            )
        return self._set_state_result(self._view_model.import_model(source))

    def download_selected(self) -> bool:
        if self._pending_handle is not None:
            return False
        model_id = self._selected_model_id()
        if not model_id:
            self.status_label.setText(_("Select a model first."))
            return False
        if self._job_runner is not None:
            self._download_active = True
            self.progress_bar.setRange(0, 0)
            self.progress_bar.show()
            return self._run_result_job(
                "local_model_download",
                lambda token: self._view_model.download_model(model_id, cancellation=token, progress=self.download_progress.emit),
                self._complete_state_job,
                _("Downloading model..."),
                cancellable=True,
            )
        return self._set_state_result(self._view_model.download_model(model_id))

    def verify_selected(self) -> bool:
        model_id = self._selected_model_id()
        if not model_id:
            self.status_label.setText(_("Select a model first."))
            return False
        if self._job_runner is not None:
            return self._run_result_job(
                "local_model_verify",
                lambda: self._view_model.verify_model(model_id),
                self._complete_verify,
                _("Verifying model..."),
            )
        result = self._view_model.verify_model(model_id)
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return False
        self._show_verify_result(result.value)
        return result.value.verified

    def select_current(self) -> bool:
        model_id = self._selected_model_id()
        if not model_id:
            self.status_label.setText(_("Select a model first."))
            return False
        if self._job_runner is not None:
            return self._run_state_job("local_model_select", lambda: self._view_model.select_model(model_id),
                                       _("Please wait for the current operation."))
        return self._set_state_result(self._view_model.select_model(model_id))

    def delete_selected(self) -> bool:
        model_id = self._selected_model_id()
        if not model_id:
            self.status_label.setText(_("Select a model first."))
            return False
        item = self._selected_item()
        if QMessageBox.question(self, _("Delete"),
            _("Delete model {model}?").format(model=item.entry.display_name if item else model_id),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return False
        if self._job_runner is not None:
            return self._run_state_job("local_model_delete", lambda: self._view_model.delete_model(model_id),
                                       _("Please wait for the current operation."))
        return self._set_state_result(self._view_model.delete_model(model_id))

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        root.setSpacing(16)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel(_("Local Models")), 1)
        self.refresh_button = QToolButton()
        self.refresh_button.setToolTip(_("Refresh"))
        self.refresh_button.setAccessibleName(_("Refresh"))
        self.import_button = QPushButton(_("Import .gguf"))
        toolbar.addWidget(self.refresh_button)
        toolbar.addWidget(self.import_button)
        root.addLayout(toolbar)
        body = QHBoxLayout()
        body.setSpacing(20)

        self.model_list = QListWidget()
        self.model_list.setObjectName("local_model_list_widget")
        self.model_list.setMinimumWidth(280)
        self.model_list.setItemDelegate(TwoLineItemDelegate(self.model_list))
        self.model_list.setSpacing(4)
        self.model_list.setFrameShape(QFrame.Shape.StyledPanel)
        self.model_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body.addWidget(self.model_list, 1)
        details = QVBoxLayout()
        details.setSpacing(12)
        self.details_scroll = QScrollArea()
        self.details_scroll.setWidgetResizable(True)
        self.details_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.details_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        panel = QWidget()
        info = QVBoxLayout(panel)
        info.setContentsMargins(0, 0, 8, 0)
        info.setSpacing(12)
        self.model_name_label = self._detail_label()
        self.model_name_label.setProperty("role", "section_heading")
        self.model_status_label = self._detail_label()
        self.model_status_label.setProperty("role", "secondary")
        self.description_label = self._detail_label()
        info.addWidget(self.model_name_label)
        info.addWidget(self.model_status_label)
        info.addWidget(self.description_label)
        form = QFormLayout()
        form.setSpacing(12)
        self.file_label, self.size_label, self.ram_label = (self._detail_label() for _index in range(3))
        self.context_label, self.output_label, self.license_label = (self._detail_label() for _index in range(3))
        for caption, label in ((_("File"), self.file_label), (_("Estimated size"), self.size_label),
                               (_("Estimated RAM"), self.ram_label), (_("Context"), self.context_label),
                               (_("Output"), self.output_label),
                               (_("License"), self.license_label)):
            form.addRow(caption, label)
        info.addLayout(form)
        info.addStretch(1)
        self.details_scroll.setWidget(panel)
        details.addWidget(self.details_scroll, 1)
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("model_download_progress_bar")
        self.progress_bar.hide()
        details.addWidget(self.progress_bar)

        actions = QHBoxLayout()
        self.download_button = QPushButton(_("Download"))
        self.verify_button = QPushButton(_("Verify"))
        self.select_button = QPushButton(_("Use model"))
        self.select_button.setProperty("variant", "primary")
        self.delete_button = QPushButton(_("Delete"))
        for button in (self.download_button, self.verify_button, self.delete_button):
            actions.addWidget(button)
        details.addLayout(actions)
        details.addWidget(self.select_button)
        body.addLayout(details, 1)
        root.addLayout(body, 1)

        bottom = QHBoxLayout()
        self.status_label = StatusLabel()
        self.close_button = QPushButton(_("Close"))
        bottom.addWidget(self.status_label, 1)
        bottom.addStretch()
        bottom.addWidget(self.close_button)
        root.addLayout(bottom)

        self.refresh_button.clicked.connect(self.refresh_catalog)
        self.import_button.clicked.connect(lambda: self.import_model())
        self.download_button.clicked.connect(self.download_selected)
        self.verify_button.clicked.connect(self.verify_selected)
        self.select_button.clicked.connect(self.select_current)
        self.delete_button.clicked.connect(self.delete_selected)
        self.close_button.clicked.connect(self.accept)
        for button, icon in ((self.refresh_button, "refresh-cw"), (self.import_button, "file-input"),
                             (self.download_button, "download"), (self.verify_button, "shield-check"),
                             (self.select_button, "check"), (self.delete_button, "trash")):
            set_button_icon(button, icon)
            button.setMinimumHeight(36)
            if isinstance(button, QPushButton):
                button.setAutoDefault(False)
        self.close_button.setMinimumHeight(36)
        self.close_button.setAutoDefault(False)
        self.model_list.currentItemChanged.connect(lambda _current, _previous: self._update_details())
        self._update_details()

    def _detail_label(self):
        label = QLabel()
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        return label

    def _selected_item(self):
        model_id = self._selected_model_id()
        return next((item for item in self._state.inventory.items if item.entry.id == model_id), None) if self._state else None

    def _update_details(self):
        item = self._selected_item()
        if item is None:
            self.model_name_label.setText(_("No models found") if self._state is not None else "")
            for label in (self.model_status_label, self.description_label, self.file_label, self.size_label,
                          self.ram_label, self.context_label, self.output_label, self.license_label):
                label.clear()
        else:
            entry = item.entry
            self.model_name_label.setText(entry.display_name)
            self.model_status_label.setText(self._status_text(item))
            self.description_label.setText(entry.description_translations.get(get_language(), entry.description))
            self.file_label.setText(entry.filename)
            self.size_label.setText(_("{size} MB").format(size=entry.estimated_size_mb) if entry.estimated_size_mb else _("Unknown"))
            self.ram_label.setText(_("{ram} GB").format(ram=entry.min_ram_gb) if entry.min_ram_gb else _("Unknown"))
            self.context_label.setText(_("{count} tokens").format(count=entry.context_length))
            self.output_label.setText(_("{count} tokens").format(count=entry.max_output_tokens))
            self.license_label.setText(entry.license or _("Unknown"))
        self.download_button.setEnabled(bool(not self._busy and item and not item.available and item.entry.download_url))
        self.verify_button.setEnabled(bool(not self._busy and item and item.available))
        self.select_button.setEnabled(bool(not self._busy and item and item.verified and item.available and not item.active))
        self.delete_button.setEnabled(bool(not self._busy and item and item.available))

    def _status_text(self, item):
        if item.verified:
            status = _("Verified")
        elif not item.available:
            status = _("Not downloaded")
        else:
            status = display_error_code(item.reason) if item.reason else _("Not verified")
        return status + (" | " + _("Active") if item.active else "")

    def accept(self) -> None:
        if self._pending_handle is None:
            super().accept()
        else:
            self._pending_handle.cancel()

    def reject(self) -> None:
        if self._pending_handle is None:
            super().reject()
        else:
            self._pending_handle.cancel()

    def closeEvent(self, event) -> None:
        if self._pending_handle is not None:
            self._pending_handle.cancel()
            event.ignore()
        else:
            super().closeEvent(event)

    def _set_state_result(self, result: object) -> bool:
        if not getattr(result, "ok", False) or getattr(result, "value", None) is None:
            self._set_error(getattr(result, "error", None))
            return False
        self._state = result.value
        self._render()
        self._last_error = None
        self.status_label.setText(self._state.message)
        return True

    def _run_state_job(
        self,
        name: str,
        job: object,
        busy_message: str,
        *,
        cancellable: bool = False,
    ) -> bool:
        return self._run_result_job(name, job, self._complete_state_job, busy_message, cancellable=cancellable)

    def _run_result_job(
        self,
        name: str,
        job: object,
        callback: object,
        busy_message: str,
        *,
        cancellable: bool = False,
    ) -> bool:
        if self._pending_handle is not None:
            self.status_label.setText(_("Please wait for the current operation."))
            return False
        assert self._job_runner is not None
        self._set_busy(True)
        if not self._download_active:
            self.progress_bar.hide()
        self.status_label.setText(busy_message)
        self._pending_handle = JobHandle(
            job_id=f"{name}_pending",
            cancel=lambda: None,
        )
        try:
            handle = self._job_runner.submit(
                name,
                lambda token: job(token) if cancellable else job(),
                on_complete=callback,
            )
        except Exception:
            self._pending_handle = None
            self._set_busy(False)
            self._download_active = False
            self.progress_bar.hide()
            self._set_error(InfrastructureError("local_model_operation_failed", "local_model_operation_failed"))
            return False
        if self._pending_handle is not None:
            self._pending_handle = handle
        return True

    def _complete_state_job(self, result: object) -> None:
        self._pending_handle = None
        self._set_busy(False)
        self._set_state_result(result)
        if self._download_active:
            if getattr(result, "ok", False):
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(100)
            else:
                self.progress_bar.hide()
            self._download_active = False

    def _show_download_progress(self, progress):
        if not self._download_active:
            return
        if progress.phase == "verification":
            self.progress_bar.setRange(0, 0)
            self.status_label.setText(_("Verifying downloaded file..."))
        elif progress.total_bytes:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(min(99, int(progress.received_bytes * 100 / progress.total_bytes)))
            self.progress_bar.setToolTip(_("{received} MB of {total} MB").format(
                received=f"{progress.received_bytes / 1024 ** 2:.1f}", total=f"{progress.total_bytes / 1024 ** 2:.1f}"))
        else:
            self.progress_bar.setRange(0, 0)

    def _complete_verify(self, result: object) -> None:
        self._pending_handle = None
        self._set_busy(False)
        if not getattr(result, "ok", False) or getattr(result, "value", None) is None:
            self._set_error(getattr(result, "error", None))
            return
        self._show_verify_result(result.value)

    def _show_verify_result(self, status: object) -> None:
        message = _("Model verified.") if status.verified else display_error_code(status.reason)
        self.status_label.setText(message)
        if self._state is not None:
            items = tuple(replace(item, available=status.available, verified=status.verified, reason=status.reason)
                          if item.entry.id == status.model_id else item for item in self._state.inventory.items)
            self._state = replace(self._state, inventory=replace(self._state.inventory, items=items))
            self._render()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.close_button.setEnabled(True)
        self.close_button.setText(_("Cancel") if busy else _("Close"))
        self.model_list.setEnabled(not busy)
        for button in (self.refresh_button, self.import_button):
            button.setEnabled(not busy)
        self._update_details()

    def _render(self) -> None:
        selected_id = self._selected_model_id()
        with QSignalBlocker(self.model_list):
            self.model_list.clear()
        if self._state is None:
            return
        for item in self._state.inventory.items:
            label = item.entry.display_name + "\n" + self._status_text(item)
            list_item = QListWidgetItem(label)
            list_item.setData(Qt.ItemDataRole.UserRole, item.entry.id)
            entry = item.entry
            description = entry.description_translations.get(get_language(), entry.description)
            details = [description]
            if entry.min_ram_gb:
                details.append(_("Estimated RAM: {ram} GB").format(ram=entry.min_ram_gb))
            details.append(_("Context: {context} tokens; output: {output} tokens").format(
                context=entry.context_length, output=entry.max_output_tokens))
            if entry.license:
                details.append(_("License: {license}").format(license=entry.license))
            list_item.setToolTip("\n".join(part for part in details if part))
            self.model_list.addItem(list_item)
        row = next((row for row, item in enumerate(self._state.inventory.items) if item.entry.id == selected_id), 0)
        if self.model_list.count():
            self.model_list.setCurrentRow(row)
        self._update_details()

    def _selected_model_id(self) -> str | None:
        item = self.model_list.currentItem()
        if item is None:
            return None
        return str(item.data(Qt.ItemDataRole.UserRole) or "").strip() or None

    def _choose_model_file(self) -> Path | None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            _("Import .gguf"),
            "",
            _("GGUF Model (*.gguf)"),
        )
        return Path(path) if path else None

    def _set_error(self, error: AppError | None) -> None:
        self._last_error = None if isinstance(error, CancellationError) else error
        self.status_label.setText(display_error_message(error))
