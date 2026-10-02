"""Local model workflow controller."""

from __future__ import annotations

from collections.abc import Callable
from PySide6.QtCore import QTimer

from PySide6.QtWidgets import QWidget

from worklogger.app.job_runner import JobRunner
from worklogger.presentation.local_models.dialog import LocalModelsDialog
from worklogger.presentation.viewmodels import LocalModelManagerViewModel


LocalModelsDialogFactory = Callable[
    [LocalModelManagerViewModel, QWidget | None],
    LocalModelsDialog,
]


class LocalModelsWorkflowController:
    def __init__(
        self,
        view_model: LocalModelManagerViewModel,
        *,
        job_runner: JobRunner | None = None,
        dialog_factory: LocalModelsDialogFactory | None = None,
    ) -> None:
        self._view_model = view_model
        self._job_runner = job_runner
        self._dialog_factory = dialog_factory

    @property
    def view_model(self) -> LocalModelManagerViewModel:
        return self._view_model

    def open(self, parent: QWidget | None = None) -> LocalModelsDialog:
        return self._open(parent)

    def open_for_import(self, parent: QWidget | None = None) -> LocalModelsDialog:
        return self._open(parent, action="import")

    def open_for_download(self, parent: QWidget | None = None) -> LocalModelsDialog:
        return self._open(parent, action="download")

    def _open(self, parent: QWidget | None, *, action: str = "") -> LocalModelsDialog:
        if self._dialog_factory is None:
            dialog = LocalModelsDialog(
                self._view_model,
                parent,
                job_runner=self._job_runner,
            )
        else:
            dialog = self._dialog_factory(self._view_model, parent)
        if action == "import":
            def import_model() -> None:
                if not dialog.import_model():
                    dialog.refresh()

            QTimer.singleShot(0, dialog, import_model)
        elif action == "download":
            dialog.download_button.setFocus()
            QTimer.singleShot(0, dialog, dialog.refresh_catalog)
        else:
            dialog.refresh()
        dialog.exec()
        return dialog
