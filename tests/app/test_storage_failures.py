"""Application error boundaries preserve safe, typed results."""

from datetime import date
import sqlite3
import unittest
from unittest.mock import Mock

from worklogger.app.queries.work_log_queries import GetAllWorkLogsQuery, GetMonthRecordsQuery
from worklogger.app.queries.note_queries import GetDailyNoteQuery
from worklogger.app.queries.calendar_queries import GetCalendarEventsForRangeQuery
from worklogger.app.queries.local_model_queries import ListLocalModelsQuery
from worklogger.app.queries.report_queries import GetReportForPeriodQuery, ListReportsQuery
from worklogger.app.use_cases.reports import GetReportForPeriodHandler, ListReportsHandler
from worklogger.app.use_cases.work_logs import GetAllWorkLogsHandler, GetMonthRecordsHandler
from worklogger.app.use_cases.notes import GetDailyNoteHandler
from worklogger.app.use_cases.calendar import GetCalendarEventsForRangeHandler
from worklogger.app.use_cases.local_models import ListLocalModelsHandler
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result


class StorageFailureTests(unittest.TestCase):
    def test_note_size_errors_distinguish_content_limits_and_preserve_storage(self):
        from worklogger.app.use_cases.notes import DailyNotesService
        from worklogger.domain.notes.models import MAX_NOTE_CONTENT_BYTES
        from worklogger.domain.notes.preferences import NoteSharing

        notes, settings, previous = Mock(), Mock(), Mock()
        previous.list_for_day.return_value = ()
        service = DailyNotesService(user_id=1, notes=notes, settings=settings, previous_entries=previous)
        day = date(2026, 10, 25)
        for content in ("x" * (MAX_NOTE_CONTENT_BYTES + 1), "\u4e2d" * 350_000):
            self.assertEqual(service.save(day, content, "", NoteSharing()).error.code, "note_content_too_long")
            self.assertEqual(service.save_draft(day, content, "", NoteSharing()).error.code, "note_content_too_long")
        self.assertEqual(service.save_draft(day, "edited", "x" * (MAX_NOTE_CONTENT_BYTES + 1), NoteSharing()).error.code,
                         "note_content_too_long")
        notes.save.assert_not_called()
        settings.set.assert_not_called()
        previous.list_for_day.assert_not_called()
        self.assertTrue(service.save(day, "x" * MAX_NOTE_CONTENT_BYTES, "", NoteSharing()).ok)

    def test_template_size_limit_rejects_input_before_writing(self):
        from worklogger.app.commands.report_commands import SaveReportTemplateCommand
        from worklogger.app.use_cases.reports import SaveReportTemplateHandler
        repository = Mock()
        handler = SaveReportTemplateHandler(repository)
        command = SaveReportTemplateCommand(1, "en_US", "daily", "x" * (1024 * 1024 + 1))
        self.assertFalse(handler.handle(command).ok)
        repository.save.assert_not_called()

    def test_queries_and_commands_return_safe_storage_errors(self):
        day = date(2026, 10, 10)
        repository = Mock()
        for name in ("add", "get_for_day", "get_for_period", "list_for_month", "list_all", "list_for_day", "list_for_range", "get"):
            getattr(repository, name).side_effect = sqlite3.OperationalError("private diagnostic")
        cases = (
            (GetDailyNoteHandler(repository), GetDailyNoteQuery(1, day)),
            (GetMonthRecordsHandler(repository), GetMonthRecordsQuery(1, 2026, 10)),
            (GetAllWorkLogsHandler(repository), GetAllWorkLogsQuery(1)),
            (GetCalendarEventsForRangeHandler(repository), GetCalendarEventsForRangeQuery(1, day, day)),
            (GetReportForPeriodHandler(repository), GetReportForPeriodQuery(1, "daily", day, day)),
        )
        for handler, request in cases:
            with self.subTest(handler=type(handler).__name__):
                result = handler.handle(request)
                self.assertFalse(result.ok)
                self.assertIsInstance(result.error, InfrastructureError)
                self.assertNotIn("private", result.error.message)
        store = Mock()
        store.list_models.return_value = Result.success(())
        handler = ListLocalModelsHandler(store=store, settings=repository)
        self.assertIsInstance(handler.handle(ListLocalModelsQuery(1)).error, InfrastructureError)

    def test_report_history_rejects_partial_or_reversed_ranges_before_reading(self):
        repository = Mock()
        handler = ListReportsHandler(repository)
        start, end = date(2026, 10, 1), date(2026, 10, 12)
        for bounds in ((start, None), (None, end), (end, start)):
            result = handler.handle(ListReportsQuery(1, "daily", *bounds))
            self.assertEqual(result.error.code, "report_period_invalid")
        repository.list_range.assert_not_called()
        repository.list_by_type.assert_not_called()
