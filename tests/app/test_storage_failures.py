"""Application error boundaries preserve safe, typed results."""

from datetime import date
import sqlite3
import unittest
from unittest.mock import Mock

from worklogger.app.commands.quick_log_commands import AddQuickLogCommand
from worklogger.app.queries.work_log_queries import GetAllWorkLogsQuery, GetMonthRecordsQuery, GetWorkLogQuery
from worklogger.app.queries.quick_log_queries import GetQuickLogsForDayQuery, GetQuickLogsForRangeQuery
from worklogger.app.queries.calendar_queries import GetCalendarEventsForDayQuery, GetCalendarEventsForRangeQuery
from worklogger.app.queries.local_model_queries import ListLocalModelsQuery
from worklogger.app.use_cases.work_logs import GetAllWorkLogsHandler, GetMonthRecordsHandler, GetWorkLogHandler
from worklogger.app.use_cases.quick_logs import AddQuickLogHandler, GetQuickLogsForDayHandler, GetQuickLogsForRangeHandler
from worklogger.app.use_cases.calendar import GetCalendarEventsForDayHandler, GetCalendarEventsForRangeHandler
from worklogger.app.use_cases.local_models import ListLocalModelsHandler, GetLocalModelRuntimeStatusHandler
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result


class StorageFailureTests(unittest.TestCase):
    def test_content_size_limits_reject_input_before_writing(self):
        from worklogger.app.commands.note_commands import SaveDailyNoteCommand
        from worklogger.app.commands.report_commands import SaveReportTemplateCommand
        from worklogger.app.use_cases.notes import SaveDailyNoteHandler
        from worklogger.app.use_cases.reports import SaveReportTemplateHandler
        repository = Mock()
        day = date(2026, 10, 10)
        cases = (
            (AddQuickLogHandler(repository), AddQuickLogCommand(1, day, "x" * 16_001)),
            (SaveDailyNoteHandler(repository), SaveDailyNoteCommand(1, day, "\u4e2d" * 350_000)),
            (SaveReportTemplateHandler(repository), SaveReportTemplateCommand(1, "en_US", "daily", "x" * (1024 * 1024 + 1))),
        )
        for handler, command in cases:
            self.assertFalse(handler.handle(command).ok)
        repository.add.assert_not_called()
        repository.save.assert_not_called()

    def test_queries_and_commands_return_safe_storage_errors(self):
        day = date(2026, 10, 10)
        repository = Mock()
        for name in ("add", "get_for_day", "list_for_month", "list_all", "list_for_day", "list_for_range", "get"):
            getattr(repository, name).side_effect = sqlite3.OperationalError("private diagnostic")
        cases = (
            (GetWorkLogHandler(repository), GetWorkLogQuery(1, day)),
            (GetMonthRecordsHandler(repository), GetMonthRecordsQuery(1, 2026, 10)),
            (GetAllWorkLogsHandler(repository), GetAllWorkLogsQuery(1)),
            (AddQuickLogHandler(repository), AddQuickLogCommand(1, day, "Work")),
            (GetQuickLogsForDayHandler(repository), GetQuickLogsForDayQuery(1, day)),
            (GetQuickLogsForRangeHandler(repository), GetQuickLogsForRangeQuery(1, day, day)),
            (GetCalendarEventsForDayHandler(repository), GetCalendarEventsForDayQuery(1, day)),
            (GetCalendarEventsForRangeHandler(repository), GetCalendarEventsForRangeQuery(1, day, day)),
        )
        for handler, request in cases:
            with self.subTest(handler=type(handler).__name__):
                result = handler.handle(request)
                self.assertFalse(result.ok)
                self.assertIsInstance(result.error, InfrastructureError)
                self.assertNotIn("private", result.error.message)
        store = Mock()
        store.list_models.return_value = Result.success(())
        for handler in (ListLocalModelsHandler(store=store, settings=repository),
                        GetLocalModelRuntimeStatusHandler(store=store, settings=repository)):
            self.assertIsInstance(handler.handle(ListLocalModelsQuery(1)).error, InfrastructureError)
