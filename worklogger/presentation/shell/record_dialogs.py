"""Account record dialogs and their presentation lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid

from worklogger.app.job_runner import JobRunner
from worklogger.domain.worklog.models import WorkLog

if TYPE_CHECKING:
    from worklogger.presentation.viewmodels.analytics import AnalyticsViewModel
    from worklogger.presentation.viewmodels.time_entries import TimeEntryViewModel
    from worklogger.presentation.widgets.record_search import RecordSearchDialog


class RecordDialogController(QObject):
    def __init__(self, parent: QWidget, records: TimeEntryViewModel, *,
                 analytics: AnalyticsViewModel | None,
                 current_month: Callable[[], date], selected_day: Callable[[], date],
                 select_record: Callable[[WorkLog], bool], records_changed: Callable[[], None],
                 job_runner: JobRunner | None = None):
        super().__init__(parent)
        self._window, self._records, self._analytics = parent, records, analytics
        self._current_month, self._selected_day = current_month, selected_day
        self._select_record, self._records_changed = select_record, records_changed
        self._job_runner = job_runner
        self._search_dialog: RecordSearchDialog | None = None
        self._project_dialog = None

    @property
    def search_dialog(self) -> RecordSearchDialog | None:
        if self._search_dialog is not None and not isValid(self._search_dialog):
            self._search_dialog = None
        return self._search_dialog

    def open_search(self) -> None:
        from worklogger.presentation.widgets.record_search import RecordSearchDialog

        if not self._records.search_available:
            return
        dialog = self.search_dialog
        if dialog is not None:
            dialog.raise_()
            dialog.activateWindow()
            return
        dialog = RecordSearchDialog(self._records, self._current_month(), self._window,
            job_runner=self._job_runner, selection_handler=self._select_record)
        dialog.records_changed.connect(self._records_changed)
        dialog.finished.connect(self._search_finished)
        dialog.finished.connect(dialog.deleteLater)
        self._search_dialog = dialog
        dialog.open()

    def _search_finished(self) -> None:
        self._search_dialog = None

    def open_project_analytics(self) -> None:
        from worklogger.presentation.widgets.project_analytics import ProjectAnalyticsDialog

        if self._analytics is None or not self._records.search_available:
            return
        if self._project_dialog is not None and isValid(self._project_dialog):
            self._project_dialog.raise_()
            self._project_dialog.activateWindow()
            return
        dialog = ProjectAnalyticsDialog(self._analytics, self._records, self._selected_day(), self._window,
            job_runner=self._job_runner, selection_handler=self._select_record)
        dialog.records_changed.connect(self._records_changed)
        self._project_dialog = dialog
        dialog.finished.connect(self._project_finished)
        dialog.finished.connect(dialog.deleteLater)
        dialog.open()

    def _project_finished(self):
        self._project_dialog = None
