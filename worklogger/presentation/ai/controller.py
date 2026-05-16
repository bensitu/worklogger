"""AI Assist workflow controller."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from PySide6.QtWidgets import QWidget

from worklogger.app.job_runner import JobRunner
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
        *,
        job_runner: JobRunner | None = None,
        dialog_factory: AiAssistDialogFactory | None = None,
    ) -> None:
        self._view_model = view_model
        self._job_runner = job_runner
        self._dialog_factory = dialog_factory

    def open(self, day: date, parent: QWidget | None = None) -> AiAssistDialog:
        if self._dialog_factory is None:
            dialog = AiAssistDialog(
                self._view_model,
                day,
                parent,
                job_runner=self._job_runner,
            )
        else:
            dialog = self._dialog_factory(self._view_model, day, parent)
        dialog.exec()
        return dialog
