"""Local model workflow controller."""

from __future__ import annotations

from collections.abc import Callable

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

    def open(self, parent: QWidget | None = None) -> LocalModelsDialog:
        if self._dialog_factory is None:
            dialog = LocalModelsDialog(
                self._view_model,
                parent,
                job_runner=self._job_runner,
            )
        else:
            dialog = self._dialog_factory(self._view_model, parent)
        dialog.refresh()
        dialog.exec()
        return dialog
