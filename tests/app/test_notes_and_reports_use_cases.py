from __future__ import annotations

from datetime import date
import unittest
from unittest.mock import patch

from worklogger.app.commands.ai_commands import RewriteTextCommand
from worklogger.app.commands.report_commands import (
    GenerateReportCommand,
    ResetReportTemplateCommand,
    SaveReportTemplateCommand,
)
from worklogger.app.queries.note_queries import GetDailyNoteQuery
from worklogger.app.use_cases.ai import RewriteTextHandler
from worklogger.app.use_cases.notes import DailyNotesService, GetDailyNoteHandler
from worklogger.app.use_cases.reports import (
    GenerateReportHandler,
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
from worklogger.domain.worklog.models import WorkLog, EntryType, WorkMode


class MemoryDailyNoteRepository:
    def __init__(self) -> None:
        self.notes: dict[tuple[int, date], DailyNote] = {}

    def get_for_day(self, user_id: int, day: date) -> DailyNote:
        return self.notes.get((user_id, day), DailyNote(user_id, day, ""))

    def save(self, note: DailyNote, *, expected_content: str | None = None, **options) -> None:
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

    def list_range(self, user_id: int, start: date, end: date) -> tuple[WorkLog, ...]:
        return tuple(record for record in self.list_all(user_id) if start <= record.day <= end)

    def save(self, work_log: WorkLog, *, expected_note: str | None = None) -> None:
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
    def test_draft_recovery_supports_maximum_content_with_json_escaping(self):
        from tests.app.test_application_use_cases import MemorySettingsRepository
        from worklogger.domain.notes.models import MAX_NOTE_CONTENT_BYTES
        from worklogger.domain.notes.preferences import NoteSharing

        day = date(2026, 10, 27)
        notes, settings = MemoryDailyNoteRepository(), MemorySettingsRepository()
        service = DailyNotesService(user_id=1, notes=notes, settings=settings,
                                    previous_entries=MemoryQuickLogRepository())
        cases = (("\x00" * MAX_NOTE_CONTENT_BYTES, "\x01" * MAX_NOTE_CONTENT_BYTES),
                 ("\u4e2d" * (MAX_NOTE_CONTENT_BYTES // 3) + "x" * (MAX_NOTE_CONTENT_BYTES % 3),
                  "e" * MAX_NOTE_CONTENT_BYTES))
        for content, expected in cases:
            with self.subTest(content_prefix=repr(content[:1])):
                notes.save(DailyNote(1, day, expected))
                saved = service.save_draft(day, content, expected, NoteSharing())
                self.assertTrue(saved.ok, saved.error)
                loaded = service.load(day)
                self.assertTrue(loaded.ok, loaded.error)
                self.assertFalse(loaded.value.draft_unavailable)
                self.assertTrue(loaded.value.recovered_draft)
                self.assertEqual((loaded.value.content, loaded.value.expected_content), (content, expected))
                self.assertEqual((loaded.value.sharing, loaded.value.expected_sharing),
                                 (NoteSharing(), NoteSharing()))

    def test_draft_recovery_rejects_oversized_decoded_fields_and_serialized_payloads(self):
        import json
        from tests.app.test_application_use_cases import MemorySettingsRepository
        from worklogger.domain.notes.models import MAX_NOTE_CONTENT_BYTES
        from worklogger.domain.notes.preferences import NoteSharing, note_draft_key, note_sharing_key

        day = date(2026, 10, 27)
        notes, settings = MemoryDailyNoteRepository(), MemorySettingsRepository()
        notes.save(DailyNote(1, day, "Saved content"))
        sharing = NoteSharing(True, False)
        settings.set(1, note_sharing_key(day), sharing.encode())
        service = DailyNotesService(user_id=1, notes=notes, settings=settings,
                                    previous_entries=MemoryQuickLogRepository())
        draft = {"content": "Draft", "expected_content": "Saved content"}
        invalid = [json.dumps({**draft, field: "x" * (MAX_NOTE_CONTENT_BYTES + 1)})
                   for field in ("content", "expected_content")]
        invalid.append(json.dumps(draft) + " " * (16 * MAX_NOTE_CONTENT_BYTES))
        for raw in invalid:
            with self.subTest(serialized_length=len(raw)):
                settings.set(1, note_draft_key(day), raw)
                loaded = service.load(day)
                self.assertTrue(loaded.ok, loaded.error)
                self.assertTrue(loaded.value.draft_unavailable)
                self.assertFalse(loaded.value.recovered_draft)
                self.assertEqual((loaded.value.content, loaded.value.expected_content),
                                 ("Saved content", "Saved content"))
                self.assertEqual((loaded.value.sharing, loaded.value.expected_sharing), (sharing, sharing))
                self.assertEqual(settings.get(1, note_draft_key(day)), raw)

    def test_draft_parse_and_encoding_failures_preserve_saved_content_and_drafts(self):
        import json
        from tests.app.test_application_use_cases import MemorySettingsRepository
        from worklogger.domain.notes.preferences import NoteSharing, note_draft_key

        day = date(2026, 10, 27)
        notes, settings = MemoryDailyNoteRepository(), MemorySettingsRepository()
        note = DailyNote(1, day, "Saved content")
        notes.save(note)
        service = DailyNotesService(user_id=1, notes=notes, settings=settings,
                                    previous_entries=MemoryQuickLogRepository())
        raw = '{"content":' + "[" * 2000 + "0" + "]" * 2000 + ',"expected_content":""}'
        settings.set(1, note_draft_key(day), raw)
        loaded = service.load(day)
        self.assertTrue(loaded.ok, loaded.error)
        self.assertTrue(loaded.value.draft_unavailable)
        self.assertFalse(loaded.value.recovered_draft)
        self.assertEqual((loaded.value.content, loaded.value.expected_content), (note.content, note.content))
        self.assertEqual(settings.get(1, note_draft_key(day)), raw)
        self.assertEqual(notes.get_for_day(1, day), note)

        raw = json.dumps({"content": "\ud800", "expected_content": note.content})
        settings.set(1, note_draft_key(day), raw)
        loaded = service.load(day)
        self.assertTrue(loaded.ok, loaded.error)
        self.assertTrue(loaded.value.draft_unavailable)
        self.assertEqual(loaded.value.content, note.content)
        saved = service.save_draft(day, "\ud800", note.content, NoteSharing())
        self.assertFalse(saved.ok)
        self.assertEqual(saved.error.code, "note_save_failed")
        self.assertEqual(settings.get(1, note_draft_key(day)), raw)
        self.assertEqual(notes.get_for_day(1, day), note)

    def test_report_metadata_is_literal_without_removing_note_or_template_markdown(self):
        from worklogger.app.use_cases.report_generation import _template_values
        from worklogger.domain.projects.models import WorkContext

        day = date(2026, 10, 25)
        title = '![image](https://example.test/image)\n# heading\n<img src="https://example.test/tracker">'
        values = _template_values(report_type="daily", start=day, end=day,
            work_logs=(WorkLog(1, day, "09:00", "10:00", context=WorkContext(project_label="[Project](https://example.test)")),
                       WorkLog(1, day, note="**Intentional emphasis**\n- Follow up")),
            quick_logs=(), events=(CalendarEvent(1, 1, day, title),), standard_hours=8,
            translate=lambda value: value, display_name="**Display name**")
        self.assertNotIn("![image]", values["calendar_events"])
        self.assertNotIn("\n# heading", values["calendar_events"])
        self.assertIn(r"\<img", values["calendar_events"])
        self.assertIn(r"\!\[image\]", values["calendar_events"])
        self.assertIn(r"\[Project\]", values["projects_summary"])
        self.assertEqual(values["display_name"], r"\*\*Display name\*\*")
        self.assertIn("**Intentional emphasis**", values["notes_section"])
        self.assertTrue(render_template("# Report\n{calendar_events}", values).startswith("# Report\n"))

    def test_report_sections_separate_notes_from_work_and_omit_empty_optional_content(self):
        from worklogger.app.use_cases.report_generation import _template_values
        from worklogger.domain.worklog.rules import aggregate_days
        from worklogger.infrastructure.templates import BuiltInTemplateProvider

        day = date(2026, 10, 16)
        rows = aggregate_days((WorkLog(1, day, note="Meeting memo"),
                               WorkLog(1, day, "09:00", "17:00", note="Implemented filters")))
        values = _template_values(report_type="daily", start=day, end=day, work_logs=rows,
            quick_logs=(), events=(), standard_hours=8, translate=lambda message: message)
        content = render_template(BuiltInTemplateProvider().get_template("en_US", "daily").value, values)
        self.assertIn("09:00", content)
        self.assertIn("Implemented filters", values["work_records"])
        self.assertNotIn("Meeting memo", values["work_records"])
        self.assertEqual(content.count("Meeting memo"), 1)
        self.assertIn("## Notes", content)
        self.assertNotIn("## Calendar events", content)
        self.assertIn("## Project summary", content)
        self.assertIn("Unclassified: 8.0h", content)
        self.assertNotIn("Quick Logs", content)
        self.assertEqual(values["total_hours"], "8.0")

    def test_daily_note_service_persists_note_content(self) -> None:
        repository = MemoryDailyNoteRepository()
        from unittest.mock import Mock
        from worklogger.domain.notes.preferences import NoteSharing
        service = DailyNotesService(user_id=1, notes=repository, settings=Mock(), previous_entries=MemoryQuickLogRepository())
        saved = service.save(date(2026, 5, 14), "Daily note", "", NoteSharing())

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
                    note="Implemented notes\nContinued implementation",
                    entry_type=EntryType.NORMAL,
                    work_mode=WorkMode.REMOTE,
                ),
                WorkLog(
                    user_id=1,
                    day=date(2026, 5, 12),
                    start_time="09:00",
                    end_time="20:00",
                    break_hours=1.0,
                    note="Release support",
                    entry_type=EntryType.REMOTE,
                ),
                WorkLog(
                    user_id=1,
                    day=date(2026, 5, 13),
                    note="Vacation",
                    entry_type=EntryType.PAID_LEAVE,
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
        self.assertIn("\n  Continued implementation", content)
        self.assertIn("Release support", content)
        self.assertIn("Vacation", content)
        self.assertIn("Customer sync", content)
        self.assertIn("Design review", content)
        self.assertIn("Total 18.0 OT 2.0", content)
        self.assertIn("Normal \u00b7 Remote", content)
        with patch.object(handler, "_translator", side_effect=lambda message, **kwargs: f"{kwargs['language']}:{message}"):
            translated = handler.handle(GenerateReportCommand(1, "weekly", date(2026, 5, 11), date(2026, 5, 17),
                                                              language="ja_JP"))
        self.assertTrue(translated.ok, translated.error)
        self.assertIn("ja\\_JP:Normal \u00b7 ja\\_JP:Remote", translated.value.content)
        for repository, method in ((work_logs, "list_range"), (quick_logs, "list_for_range"), (calendar, "list_for_range")):
            with self.subTest(repository=type(repository).__name__), patch.object(repository, method, side_effect=OSError("unavailable")):
                failed = handler.handle(GenerateReportCommand(1, "daily", date(2026, 5, 11), date(2026, 5, 11)))
                self.assertFalse(failed.ok)
                self.assertEqual(failed.error.code, "report_load_failed")

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
        listed = repository.list_for_user(1, "en_US")
        loaded = repository.get(1, "en_US", "daily")
        reset = ResetReportTemplateHandler(repository).handle(
            ResetReportTemplateCommand(
                user_id=1,
                language="en_US",
                template_type="daily",
            )
        )
        after_reset = repository.get(1, "en_US", "daily")

        self.assertTrue(save.ok, save.error)
        self.assertEqual(len(listed), 1)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.content, "# Daily {{date}}")
        self.assertTrue(reset.ok, reset.error)
        self.assertIsNone(after_reset)

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

    def test_rewriting_preserves_task_constraints_in_standard_and_compact_requests(self):
        gateway = FakeGateway("Revised text")
        handler = RewriteTextHandler(gateway)
        cases = (
            ("time_entry", "Review ticket T-12 for 30 minutes.", ("short sentences",)),
            ("daily_note", "- [x] Reviewed T-12\n- [ ] Follow up", ("lists", "checklist")),
            ("daily_report", "# Work\n- Reviewed T-12\n## Risks\n- \n## Plan\n- ", ("Markdown", "empty sections")),
            ("weekly_report", "# Summary\n| Task | Time |\n| --- | --- |\n| T-12 | 1h |", ("Markdown", "tables")),
            ("monthly_report", "# Progress\n- T-12 is ongoing.", ("Markdown", "completion status")),
        )
        for context, source, constraints in cases:
            with self.subTest(context=context):
                result = handler.handle(RewriteTextCommand(1, source, context, "ja_JP", "Use a professional tone."))
                self.assertTrue(result.ok, result.error)
                request = gateway.requests[-1]
                for messages in (request.messages, request.local_messages):
                    system = messages[0]["content"]
                    self.assertIn("Do not invent achievements, risks, or plans", system)
                    self.assertIn("Keep the source text's language", system)
                    for constraint in constraints:
                        self.assertIn(constraint, system)
                    self.assertIn(source.strip(), messages[1]["content"])
                    self.assertNotIn("ja_JP", messages[1]["content"])
                    self.assertIn("Use a professional tone.", messages[-1]["content"])
                    self.assertNotIn("Use a professional tone.", system)
                self.assertLess(len(request.local_messages[0]["content"]), len(request.messages[0]["content"]))

    def test_rewriting_uses_source_language_unless_output_language_is_explicit(self):
        gateway = FakeGateway("Revised text")
        handler = RewriteTextHandler(gateway)
        source = "\u30c6\u30b9\u30c8\u3084\u308b"
        for context in ("time_entry", "daily_note", "daily_report"):
            for locale in ("en_US", "ja_JP", "zh_CN"):
                with self.subTest(context=context, locale=locale):
                    self.assertTrue(handler.handle(RewriteTextCommand(1, source, context, locale)).ok)
                    request = gateway.requests[-1]
                    for messages in (request.messages, request.local_messages):
                        self.assertIn("Do not translate unless", messages[0]["content"])
                        self.assertNotIn("Write in English", messages[0]["content"])
                        self.assertIn(f"<source>\n{source}\n</source>", messages[-1]["content"])
                        self.assertNotIn("Language:", messages[-1]["content"])
        handler.handle(RewriteTextCommand(1, source, output_language="en_US"))
        for messages in (gateway.requests[-1].messages, gateway.requests[-1].local_messages):
            self.assertIn("Write in English, as explicitly requested", messages[0]["content"])
        handler.handle(RewriteTextCommand(1, source, instructions="Translate into English."))
        self.assertIn("Translate into English.", gateway.requests[-1].messages[-1]["content"])
        self.assertIn("additional instructions explicitly request", gateway.requests[-1].messages[0]["content"])
        handler.handle(RewriteTextCommand(1, source, instructions="Use a professional tone."))
        for messages in (gateway.requests[-1].messages, gateway.requests[-1].local_messages):
            self.assertIn(f"<source>\n{source}\n</source>", messages[-1]["content"])
            self.assertIn("Keep the original language when preferences concern only tone or clarity", messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
