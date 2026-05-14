from __future__ import annotations

from dataclasses import replace
from datetime import date
import unittest

from worklogger.app.commands.ai_commands import RewriteTextCommand
from worklogger.app.commands.note_commands import SaveDailyNoteCommand
from worklogger.app.commands.report_commands import (
    GenerateReportCommand,
    ResetReportTemplateCommand,
    SaveReportTemplateCommand,
)
from worklogger.app.queries.note_queries import GetDailyNoteQuery
from worklogger.app.queries.report_queries import GetReportTemplateQuery, ListReportTemplatesQuery
from worklogger.app.use_cases.ai import RewriteTextHandler
from worklogger.app.use_cases.notes import GetDailyNoteHandler, SaveDailyNoteHandler
from worklogger.app.use_cases.reports import (
    GenerateReportHandler,
    GetReportTemplateHandler,
    ListReportTemplatesHandler,
    ResetReportTemplateHandler,
    SaveReportTemplateHandler,
)
from worklogger.app.ports import AIResponse
from worklogger.domain.calendar.models import CalendarEvent
from worklogger.domain.notes.models import DailyNote
from worklogger.domain.quicklog.models import QuickLog
from worklogger.domain.reporting.templates import ReportTemplate
from worklogger.domain.reporting.templates import render_template
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkLog, WorkType


class MemoryDailyNoteRepository:
    def __init__(self) -> None:
        self.notes: dict[tuple[int, date], DailyNote] = {}

    def get_for_day(self, user_id: int, day: date) -> DailyNote:
        return self.notes.get((user_id, day), DailyNote(user_id, day, ""))

    def save(self, note: DailyNote) -> None:
        self.notes[(note.user_id, note.day)] = note


class MemoryWorkLogRepository:
    def __init__(self, records: tuple[WorkLog, ...] = ()) -> None:
        self.records = records

    def get_for_day(self, user_id: int, day: date) -> WorkLog | None:
        for record in self.records:
            if record.user_id == user_id and record.day == day:
                return record
        return None

    def list_for_month(self, user_id: int, year: int, month: int) -> tuple[WorkLog, ...]:
        return tuple(
            record
            for record in self.records
            if record.user_id == user_id and record.day.year == year and record.day.month == month
        )

    def list_all(self, user_id: int) -> tuple[WorkLog, ...]:
        return tuple(record for record in self.records if record.user_id == user_id)

    def save(self, work_log: WorkLog) -> None:
        self.records = tuple(
            record
            for record in self.records
            if not (record.user_id == work_log.user_id and record.day == work_log.day)
        ) + (work_log,)

    def remove(self, user_id: int, day: date) -> None:
        self.records = tuple(
            record
            for record in self.records
            if not (record.user_id == user_id and record.day == day)
        )


class MemoryQuickLogRepository:
    def __init__(self, logs: tuple[QuickLog, ...] = ()) -> None:
        self.logs = logs

    def add(self, quick_log: QuickLog) -> QuickLog:
        return replace(quick_log, id=quick_log.id or len(self.logs) + 1)

    def update(self, quick_log: QuickLog) -> None:
        return None

    def remove(self, user_id: int, quick_log_id: int) -> None:
        return None

    def list_for_day(self, user_id: int, day: date) -> tuple[QuickLog, ...]:
        return tuple(log for log in self.logs if log.user_id == user_id and log.day == day)

    def list_for_range(
        self,
        user_id: int,
        start_day: date,
        end_day: date,
    ) -> tuple[QuickLog, ...]:
        return tuple(
            log
            for log in self.logs
            if log.user_id == user_id and start_day <= log.day <= end_day
        )


class MemoryCalendarRepository:
    def __init__(self, events: tuple[CalendarEvent, ...] = ()) -> None:
        self.events = events

    def list_for_day(self, user_id: int, day: date) -> tuple[CalendarEvent, ...]:
        return tuple(
            event
            for event in self.events
            if event.user_id == user_id and event.day == day
        )

    def list_for_range(
        self,
        user_id: int,
        start_day: date,
        end_day: date,
    ) -> tuple[CalendarEvent, ...]:
        return tuple(
            event
            for event in self.events
            if event.user_id == user_id and start_day <= event.day <= end_day
        )

    def replace_all(self, user_id: int, events: tuple[CalendarEvent, ...]) -> int:
        self.events = tuple(event for event in events if event.user_id == user_id)
        return len(self.events)

    def add_many(self, user_id: int, events: tuple[CalendarEvent, ...]) -> int:
        self.events += events
        return len(events)

    def clear(self, user_id: int) -> None:
        self.events = tuple(event for event in self.events if event.user_id != user_id)


class MemoryTemplateProvider:
    def get_template(
        self,
        language: str,
        template_type: str,
        user_id: int | None = None,
    ) -> Result[str]:
        del language, user_id
        return Result.success(
            "# {{date_range}}\n{{task_list}}\n{{calendar_events}}\n{{quick_logs}}\n"
            "Total {{total_hours}} OT {{overtime_hours}}"
        )


class MemoryTemplateRepository:
    def __init__(self) -> None:
        self.templates: dict[tuple[int, str, str], ReportTemplate] = {}

    def save(self, template: ReportTemplate) -> ReportTemplate:
        saved = ReportTemplate(
            id=template.id or len(self.templates) + 1,
            user_id=template.user_id,
            language=template.language,
            template_type=template.template_type,
            content=template.content,
        )
        self.templates[(saved.user_id, saved.language, saved.template_type)] = saved
        return saved

    def get(
        self,
        user_id: int,
        language: str,
        template_type: str,
    ) -> ReportTemplate | None:
        return self.templates.get((user_id, language, template_type))

    def list_for_user(
        self,
        user_id: int,
        language: str | None = None,
    ) -> tuple[ReportTemplate, ...]:
        return tuple(
            template
            for key, template in self.templates.items()
            if key[0] == user_id and (language is None or key[1] == language)
        )

    def remove(self, user_id: int, language: str, template_type: str) -> None:
        self.templates.pop((user_id, language, template_type), None)


class FakeGateway:
    def __init__(self, text: str = "rewritten") -> None:
        self.text = text
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        return Result.success(AIResponse(text=self.text, provider="fake"))


class CancelledToken:
    is_cancelled = True


class NotesReportsUseCaseTests(unittest.TestCase):
    def test_daily_note_handlers_persist_note_content(self) -> None:
        repository = MemoryDailyNoteRepository()
        saved = SaveDailyNoteHandler(repository).handle(
            SaveDailyNoteCommand(1, date(2026, 5, 14), "Daily note")
        )

        self.assertTrue(saved.ok, saved.error)
        loaded = GetDailyNoteHandler(repository).handle(
            GetDailyNoteQuery(1, date(2026, 5, 14))
        )

        self.assertTrue(loaded.ok, loaded.error)
        assert loaded.value is not None
        self.assertEqual(loaded.value.content, "Daily note")

    def test_generate_report_uses_template_worklogs_quicklogs_and_calendar(self) -> None:
        work_logs = MemoryWorkLogRepository(
            (
                WorkLog(
                    user_id=1,
                    day=date(2026, 5, 11),
                    start_time="09:00",
                    end_time="18:00",
                    break_hours=1.0,
                    note="Implemented notes",
                    work_type=WorkType.NORMAL,
                ),
                WorkLog(
                    user_id=1,
                    day=date(2026, 5, 12),
                    start_time="09:00",
                    end_time="20:00",
                    break_hours=1.0,
                    note="Release support",
                    work_type=WorkType.REMOTE,
                ),
                WorkLog(
                    user_id=1,
                    day=date(2026, 5, 13),
                    note="Vacation",
                    work_type=WorkType.PAID_LEAVE,
                ),
            )
        )
        quick_logs = MemoryQuickLogRepository(
            (
                QuickLog(
                    id=1,
                    user_id=1,
                    day=date(2026, 5, 11),
                    start_time="10:00",
                    end_time="10:30",
                    description="Design review",
                ),
            )
        )
        calendar = MemoryCalendarRepository(
            (
                CalendarEvent(
                    id=1,
                    user_id=1,
                    day=date(2026, 5, 12),
                    start_time="14:00",
                    end_time="15:00",
                    summary="Customer sync",
                ),
            )
        )
        handler = GenerateReportHandler(
            work_logs=work_logs,
            quick_logs=quick_logs,
            calendar_events=calendar,
            templates=MemoryTemplateProvider(),
        )

        report = handler.handle(
            GenerateReportCommand(
                user_id=1,
                report_type="weekly",
                period_start=date(2026, 5, 11),
                period_end=date(2026, 5, 17),
                standard_work_hours=8.0,
            )
        )

        self.assertTrue(report.ok, report.error)
        assert report.value is not None
        content = report.value.content
        self.assertIn("2026-05-11 - 2026-05-17", content)
        self.assertIn("Implemented notes", content)
        self.assertIn("Release support", content)
        self.assertIn("Vacation", content)
        self.assertIn("Customer sync", content)
        self.assertIn("Design review", content)
        self.assertIn("Total 18.0 OT 2.0", content)

    def test_template_renderer_preserves_unknown_placeholders(self) -> None:
        self.assertEqual(
            render_template("{{known}} {{missing}}", {"known": "ok"}),
            "ok {{missing}}",
        )

    def test_report_template_handlers_save_list_get_and_reset_custom_templates(self) -> None:
        repository = MemoryTemplateRepository()
        save = SaveReportTemplateHandler(repository).handle(
            SaveReportTemplateCommand(
                user_id=1,
                language="en-US",
                template_type="daily",
                content="# Daily {{date}}",
            )
        )
        listed = ListReportTemplatesHandler(repository).handle(
            ListReportTemplatesQuery(user_id=1, language="en_US")
        )
        loaded = GetReportTemplateHandler(repository).handle(
            GetReportTemplateQuery(
                user_id=1,
                language="en_US",
                template_type="daily",
            )
        )
        reset = ResetReportTemplateHandler(repository).handle(
            ResetReportTemplateCommand(
                user_id=1,
                language="en_US",
                template_type="daily",
            )
        )
        after_reset = GetReportTemplateHandler(repository).handle(
            GetReportTemplateQuery(
                user_id=1,
                language="en_US",
                template_type="daily",
            )
        )

        self.assertTrue(save.ok, save.error)
        self.assertTrue(listed.ok, listed.error)
        self.assertEqual(len(listed.value or ()), 1)
        self.assertTrue(loaded.ok, loaded.error)
        assert loaded.value is not None
        self.assertEqual(loaded.value.content, "# Daily {{date}}")
        self.assertTrue(reset.ok, reset.error)
        self.assertTrue(after_reset.ok, after_reset.error)
        self.assertIsNone(after_reset.value)

    def test_rewrite_handler_uses_gateway_and_handles_cancelled_requests(self) -> None:
        gateway = FakeGateway("Clean report")
        handler = RewriteTextHandler(gateway, model="fake-model", timeout_seconds=5.0)

        rewritten = handler.handle(
            RewriteTextCommand(
                user_id=1,
                content="rough report",
                context="weekly_report",
                language="en_US",
            )
        )
        cancelled = handler.handle(
            RewriteTextCommand(user_id=1, content="rough report"),
            cancellation_token=CancelledToken(),
        )
        disabled = RewriteTextHandler().handle(
            RewriteTextCommand(user_id=1, content="rough report")
        )

        self.assertTrue(rewritten.ok, rewritten.error)
        assert rewritten.value is not None
        self.assertEqual(rewritten.value.content, "Clean report")
        self.assertEqual(gateway.requests[0].model, "fake-model")
        self.assertFalse(cancelled.ok)
        self.assertEqual(cancelled.error.code if cancelled.error else "", "ai_rewrite_cancelled")
        self.assertFalse(disabled.ok)
        self.assertEqual(disabled.error.code if disabled.error else "", "ai_rewrite_not_configured")


if __name__ == "__main__":
    unittest.main()
