"""Local model workflow controller."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QWidget

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
        dialog_factory: LocalModelsDialogFactory | None = None,
    ) -> None:
        self._view_model = view_model
        self._dialog_factory = dialog_factory or LocalModelsDialog

    def open(self, parent: QWidget | None = None) -> LocalModelsDialog:
        dialog = self._dialog_factory(self._view_model, parent)
        dialog.refresh()
        dialog.exec()
        return dialog
