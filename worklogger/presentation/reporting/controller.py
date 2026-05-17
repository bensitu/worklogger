"""Report workflow controller."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Protocol

from PySide6.QtWidgets import QWidget

from worklogger.presentation.reporting.dialog import ReportDialog
from worklogger.presentation.viewmodels import ReportEditorViewModel


class ReportsWorkflow(Protocol):
    def open(self, day: date, parent: QWidget | None = None) -> ReportDialog:
        ...


ReportDialogFactory = Callable[
    [ReportEditorViewModel, date, QWidget | None],
    ReportDialog,
]


class ReportsWorkflowController:
    def __init__(
        self,
        view_model: ReportEditorViewModel,
        *,
        dialog_factory: ReportDialogFactory | None = None,
    ) -> None:
        self._view_model = view_model
        self._dialog_factory = dialog_factory or ReportDialog

    @property
    def view_model(self) -> ReportEditorViewModel:
        return self._view_model

    def open(self, day: date, parent: QWidget | None = None) -> ReportDialog:
        dialog = self._dialog_factory(self._view_model, day, parent)
        dialog.refresh()
        dialog.exec()
        return dialog
