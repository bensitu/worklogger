from datetime import date
import unittest

from PySide6.QtCore import QObject, Signal

from worklogger.app.job_runner import CancellationToken, JobHandle
from worklogger.domain.calendar.models import Holiday
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result
from tests.job_runner import ImmediateJobRunner
from worklogger.presentation.widgets.date_picker_holidays import DatePickerHolidaysController


class Picker(QObject):
    range_requested = Signal(object, object)

    def __init__(self):
        super().__init__()
        self.holidays = {}
        self.error = ""
        self.start, self.end = date(2026, 9, 27), date(2026, 11, 7)

    def request_holidays(self):
        self.range_requested.emit(self.start, self.end)

    def set_holidays(self, holidays):
        self.holidays, self.error = dict(holidays), ""

    def set_holiday_error(self, message):
        self.error = message


class Handler:
    def __init__(self):
        self.calls = []
        self.fail = False

    def handle(self, query):
        self.calls.append(query)
        if self.fail:
            return Result.failure(InfrastructureError("holiday_load_failed", "holiday_load_failed"))
        return Result.success((Holiday(date(2026, 10, 12), query.country),))


class DeferredRunner:
    def __init__(self):
        self.jobs = []

    def submit(self, name, job, *, on_complete):
        token = CancellationToken()
        self.jobs.append((job, on_complete, token))
        return JobHandle(str(len(self.jobs)), token.cancel)

    def complete(self, index):
        job, callback, token = self.jobs[index]
        callback(job(token))


class DatePickerHolidaysTests(unittest.TestCase):
    def test_region_changes_and_disable_reject_obsolete_results(self):
        picker, handler, runner = Picker(), Handler(), DeferredRunner()
        controller = DatePickerHolidaysController(picker, handler, country="JP", region="US/CA", job_runner=runner)
        picker.request_holidays()
        controller.configure(enabled=True, region="AU/VIC")
        runner.complete(1)
        self.assertEqual(picker.holidays, {date(2026, 10, 12): "AU"})
        self.assertEqual(handler.calls[0].subdivision, "VIC")
        runner.complete(0)
        self.assertEqual(handler.calls[-1].subdivision, "CA")
        self.assertEqual(picker.holidays, {date(2026, 10, 12): "AU"})
        controller.configure(enabled=False, region="AU/VIC")
        self.assertEqual(picker.holidays, {})
        runner.complete(1)
        self.assertEqual(picker.holidays, {})
        controller.dispose()

    def test_cached_ranges_retry_failures_and_use_the_default_country(self):
        picker, handler = Picker(), Handler()
        controller = DatePickerHolidaysController(picker, handler, country="JP", job_runner=ImmediateJobRunner())
        handler.fail = True
        picker.request_holidays()
        self.assertTrue(picker.error)
        self.assertEqual(picker.holidays, {})
        handler.fail = False
        picker.request_holidays()
        self.assertEqual(picker.holidays, {date(2026, 10, 12): "JP"})
        self.assertEqual(picker.error, "")
        picker.request_holidays()
        self.assertEqual(len(handler.calls), 2)
        self.assertEqual((handler.calls[0].start_day, handler.calls[0].end_day), (picker.start, picker.end))
        controller.dispose()
        picker.request_holidays()
        self.assertEqual(len(handler.calls), 2)
