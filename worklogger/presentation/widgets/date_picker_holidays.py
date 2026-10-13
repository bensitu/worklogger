"""Asynchronous holiday loading for a date picker, with bounded range caching."""

from collections import OrderedDict

from PySide6.QtCore import QCoreApplication, QObject, Slot
from shiboken6 import isValid

from worklogger.app.queries.calendar_queries import GetHolidaysForRangeQuery
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.job_runner import QtJobRunner


class DatePickerHolidaysController(QObject):
    def __init__(self, picker, handler, *, country="", enabled=True, region="", job_runner=None):
        super().__init__(picker)
        self._picker, self._handler, self._runner = picker, handler, job_runner
        self._country, self._enabled, self._region = country, enabled, region
        self._cache = OrderedDict()
        self._version = 0
        self._handle = None
        self._disposed = False
        picker.range_requested.connect(self.load_range)
        picker.destroyed.connect(self.dispose)

    def configure(self, *, enabled, region):
        if (enabled, region) == (self._enabled, self._region):
            return
        self._enabled, self._region = enabled, region
        self._cancel()
        self._picker.set_holidays({})
        self._picker.request_holidays()

    def _cancel(self):
        self._version += 1
        if self._handle is not None:
            self._handle.cancel()
        self._handle = None

    @Slot(object, object)
    def load_range(self, start, end):
        if self._disposed:
            return
        self._cancel()
        if not self._enabled or self._handler is None:
            self._picker.set_holidays({})
            return
        country, _separator, subdivision = self._region.partition("/")
        query = GetHolidaysForRangeQuery(country or self._country, start, end, subdivision or None)
        if query in self._cache:
            self._cache.move_to_end(query)
            self._picker.set_holidays(self._cache[query])
            return
        version = self._version
        if self._runner is None:
            self._runner = QtJobRunner(QCoreApplication.instance())

        def complete(result):
            if not isValid(self) or self._disposed or version != self._version:
                return
            self._handle = None
            if not result.ok:
                error = result.error or InfrastructureError("holiday_load_failed", "holiday_load_failed")
                self._picker.set_holiday_error(display_error_message(error))
                return
            holidays = {holiday.day: holiday.name for holiday in result.value or ()}
            self._cache[query] = holidays
            if len(self._cache) > 8:
                self._cache.popitem(last=False)
            self._picker.set_holidays(holidays)

        try:
            handle = self._runner.submit("date_picker_holidays", lambda _token: self._handler.handle(query), on_complete=complete)
            if version == self._version and query not in self._cache:
                self._handle = handle
        except RuntimeError:
            complete(Result.failure(InfrastructureError("holiday_load_failed", "holiday_load_failed")))

    @Slot()
    def dispose(self):
        if getattr(self, "_disposed", True):
            return
        self._disposed = True
        self._cancel()
