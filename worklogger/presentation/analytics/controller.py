"""Analytics workflow controller."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from PySide6.QtWidgets import QWidget

from worklogger.presentation.analytics.dialog import AnalyticsDialog
from worklogger.presentation.viewmodels import AnalyticsViewModel


AnalyticsDialogFactory = Callable[
    [AnalyticsViewModel, date, QWidget | None],
    AnalyticsDialog,
]


class AnalyticsWorkflowController:
    def __init__(
        self,
        view_model: AnalyticsViewModel,
        dialog_factory: AnalyticsDialogFactory | None = None,
    ) -> None:
        self._view_model = view_model
        self._dialog_factory = dialog_factory or AnalyticsDialog

    @property
    def view_model(self) -> AnalyticsViewModel:
        return self._view_model

    def open(self, day: date, parent: QWidget | None = None) -> AnalyticsDialog:
        dialog = self._dialog_factory(self._view_model, day, parent)
        dialog.refresh()
        dialog.exec()
        return dialog
