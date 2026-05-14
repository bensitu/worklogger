"""AI Assist workflow controller."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from PySide6.QtWidgets import QWidget

from worklogger.presentation.ai.dialog import AiAssistDialog
from worklogger.presentation.viewmodels import AiAssistViewModel


AiAssistDialogFactory = Callable[
    [AiAssistViewModel, date, QWidget | None],
    AiAssistDialog,
]


class AiAssistWorkflowController:
    def __init__(
        self,
        view_model: AiAssistViewModel,
        dialog_factory: AiAssistDialogFactory | None = None,
    ) -> None:
        self._view_model = view_model
        self._dialog_factory = dialog_factory or AiAssistDialog

    def open(self, day: date, parent: QWidget | None = None) -> AiAssistDialog:
        dialog = self._dialog_factory(self._view_model, day, parent)
        dialog.exec()
        return dialog

