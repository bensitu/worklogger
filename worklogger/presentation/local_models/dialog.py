"""Local model management dialog."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from worklogger.app.job_runner import JobHandle, JobRunner
from worklogger.domain.shared.errors import AppError
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.viewmodels import (
    LocalModelManagerState,
    LocalModelManagerViewModel,
)


class LocalModelsDialog(QDialog):
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
        self._job_runner = job_runner
        self._pending_handle: JobHandle[object] | None = None
        self.setObjectName("local_models_dialog")
        self.setWindowTitle(_("Local Models"))
        self._build_ui()

    @property
    def last_error(self) -> AppError | None:
        return self._last_error

    @property
    def state(self) -> LocalModelManagerState | None:
        return self._state

    def refresh(self) -> bool:
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
        model_id = self._selected_model_id()
        if not model_id:
            self.status_label.setText(_("Select a model first."))
            return False
        if self._job_runner is not None:
            return self._run_state_job(
                "local_model_download",
                lambda: self._view_model.download_model(model_id),
                _("Downloading model..."),
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
        return self._set_state_result(self._view_model.select_model(model_id))

    def delete_selected(self) -> bool:
        model_id = self._selected_model_id()
        if not model_id:
            self.status_label.setText(_("Select a model first."))
            return False
        return self._set_state_result(self._view_model.delete_model(model_id))

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        self.model_list = QListWidget()
        self.model_list.setObjectName("local_model_list_widget")
        root.addWidget(self.model_list, 1)

        actions = QHBoxLayout()
        self.refresh_button = QPushButton(_("Refresh"))
        self.import_button = QPushButton(_("Import .gguf"))
        self.download_button = QPushButton(_("Download"))
        self.verify_button = QPushButton(_("Verify"))
        self.select_button = QPushButton(_("Select"))
        self.delete_button = QPushButton(_("Delete"))
        for button in (
            self.refresh_button,
            self.import_button,
            self.download_button,
            self.verify_button,
            self.select_button,
            self.delete_button,
        ):
            actions.addWidget(button)
        root.addLayout(actions)

        bottom = QHBoxLayout()
        self.status_label = QLabel("")
        self.close_button = QPushButton(_("Close"))
        bottom.addWidget(self.status_label, 1)
        bottom.addWidget(self.close_button)
        root.addLayout(bottom)

        self.refresh_button.clicked.connect(self.refresh_catalog)
        self.import_button.clicked.connect(lambda: self.import_model())
        self.download_button.clicked.connect(self.download_selected)
        self.verify_button.clicked.connect(self.verify_selected)
        self.select_button.clicked.connect(self.select_current)
        self.delete_button.clicked.connect(self.delete_selected)
        self.close_button.clicked.connect(self.accept)

    def _set_state_result(self, result: object) -> bool:
        if not getattr(result, "ok", False) or getattr(result, "value", None) is None:
            self._set_error(getattr(result, "error", None))
            return False
        self._state = result.value
        self._render()
        self.status_label.setText(self._state.message or _("Ready"))
        return True

    def _run_state_job(
        self,
        name: str,
        job: object,
        busy_message: str,
    ) -> bool:
        return self._run_result_job(name, job, self._complete_state_job, busy_message)

    def _run_result_job(
        self,
        name: str,
        job: object,
        callback: object,
        busy_message: str,
    ) -> bool:
        if self._pending_handle is not None:
            self.status_label.setText(_("Please wait for the current operation."))
            return False
        assert self._job_runner is not None
        self._set_busy(True)
        self.status_label.setText(busy_message)
        self._pending_handle = JobHandle(
            job_id=f"{name}_pending",
            cancel=lambda: None,
        )
        handle = self._job_runner.submit(
            name,
            lambda _token: job(),
            on_complete=callback,
        )
        if self._pending_handle is not None:
            self._pending_handle = handle
        return True

    def _complete_state_job(self, result: object) -> None:
        self._pending_handle = None
        self._set_busy(False)
        self._set_state_result(result)

    def _complete_verify(self, result: object) -> None:
        self._pending_handle = None
        self._set_busy(False)
        if not getattr(result, "ok", False) or getattr(result, "value", None) is None:
            self._set_error(getattr(result, "error", None))
            return
        self._show_verify_result(result.value)

    def _show_verify_result(self, status: object) -> None:
        message = _("Model verified.") if status.verified else status.reason
        self.status_label.setText(message)

    def _set_busy(self, busy: bool) -> None:
        for button in (
            self.refresh_button,
            self.import_button,
            self.download_button,
            self.verify_button,
            self.select_button,
            self.delete_button,
        ):
            button.setEnabled(not busy)

    def _render(self) -> None:
        self.model_list.clear()
        if self._state is None:
            return
        for item in self._state.inventory.items:
            status = _("Ready") if item.verified else _("Not downloaded")
            active = _("Active") if item.active else ""
            label = " | ".join(
                part
                for part in (
                    item.entry.display_name,
                    status,
                    active,
                )
                if part
            )
            list_item = QListWidgetItem(label)
            list_item.setData(256, item.entry.id)
            self.model_list.addItem(list_item)

    def _selected_model_id(self) -> str | None:
        item = self.model_list.currentItem()
        if item is None:
            return None
        return str(item.data(256) or "").strip() or None

    def _choose_model_file(self) -> Path | None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            _("Import .gguf"),
            "",
            _("GGUF Model (*.gguf)"),
        )
        return Path(path) if path else None

    def _set_error(self, error: AppError | None) -> None:
        self._last_error = error
        self.status_label.setText(display_error_message(error))
