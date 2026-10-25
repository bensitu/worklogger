"""Background report history loading with stale-result rejection."""

from PySide6.QtCore import QObject

from worklogger.domain.reporting.history import ReportHistoryPage
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import _
from worklogger.presentation.job_runner import owned_callback


class ReportHistoryController(QObject):
    def __init__(self, panel, model, runner, show_error, parent=None):
        super().__init__(parent)
        self.panel, self.model, self.runner = panel, model, runner
        self.show_error = show_error
        self._revision = 0
        self._busy = False
        self._pending = None
        panel.filters_changed.connect(self._invalidate)
        panel.query_requested.connect(self._load)
        panel.more_requested.connect(lambda: self._load(append=True))

    def _invalidate(self):
        self._revision += 1
        self.panel.set_loading(True)

    def refresh(self):
        self._invalidate()
        self._load()

    def _load(self, *, append=False):
        self.panel._search_timer.stop()
        if self._busy:
            self._pending = append if self._pending is None else self._pending and append
            return
        try:
            criteria = self.panel.criteria()
        except (TypeError, ValueError):
            self.panel.set_loading(False)
            self.panel.count_label.setText(_("Invalid date range"))
            return
        cursor = self.panel.next_cursor if append else None
        if append and cursor is None:
            return
        revision = self._revision
        self._busy = True
        self.panel.set_loading(True)
        position = self.panel.scroll_area.verticalScrollBar().value()

        def complete(result):
            self._busy = False
            pending, self._pending = self._pending, None
            if pending is not None and (not pending or revision != self._revision):
                self._load()
                return
            if revision != self._revision:
                return
            if not result.ok or result.value is None:
                self.panel.set_loading(False)
                self.panel.count_label.setText(_("Could not load reports"))
                self.show_error(result.error)
                return
            self.panel.set_page(result.value, append=append)
            self.panel.set_loading(False)
            if append:
                self.panel.scroll_area.verticalScrollBar().setValue(position)
            if pending:
                self._load(append=True)

        try:
            self.runner.submit("search_report_history", lambda _token: self.model.browse_history(criteria, cursor=cursor)
                               if self.model is not None else Result.success(ReportHistoryPage()),
                               on_complete=owned_callback(self, complete))
        except Exception:
            complete(Result.failure(InfrastructureError("report_history_failed", "report_history_failed")))
