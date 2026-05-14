"""Quick Log workflow controller."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from PySide6.QtWidgets import QWidget

from worklogger.presentation.quick_logs.dialog import QuickLogDialog
from worklogger.presentation.viewmodels import QuickLogEditorViewModel


QuickLogDialogFactory = Callable[
    [QuickLogEditorViewModel, date, QWidget | None],
    QuickLogDialog,
]


class QuickLogsWorkflowController:
    def __init__(
        self,
        view_model: QuickLogEditorViewModel,
        dialog_factory: QuickLogDialogFactory | None = None,
    ) -> None:
        self._view_model = view_model
        self._dialog_factory = dialog_factory or QuickLogDialog

    def open(self, day: date, parent: QWidget | None = None) -> QuickLogDialog:
        dialog = self._dialog_factory(self._view_model, day, parent)
        dialog.refresh()
        dialog.exec()
        return dialog

