"""Identity workflow controller."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QWidget

from worklogger.presentation.identity.dialog import IdentityDialog
from worklogger.presentation.viewmodels import IdentityManagementViewModel


IdentityDialogFactory = Callable[
    [IdentityManagementViewModel, QWidget | None],
    IdentityDialog,
]


class IdentityWorkflowController:
    def __init__(
        self,
        view_model: IdentityManagementViewModel,
        dialog_factory: IdentityDialogFactory | None = None,
    ) -> None:
        self._view_model = view_model
        self._dialog_factory = dialog_factory or IdentityDialog

    def open(self, parent: QWidget | None = None) -> IdentityDialog:
        dialog = self._dialog_factory(self._view_model, parent)
        dialog.refresh()
        dialog.exec()
        return dialog
