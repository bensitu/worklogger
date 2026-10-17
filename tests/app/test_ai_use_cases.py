from __future__ import annotations

from datetime import date
import json
import unittest
from unittest.mock import Mock

from worklogger.app.commands.ai_commands import SendAiChatMessageCommand
from worklogger.app.queries.ai_queries import BuildAiContextQuery
from worklogger.app.queries.calendar_queries import GetCalendarEventsForRangeQuery
from worklogger.app.queries.note_queries import GetDailyNoteQuery
from worklogger.app.queries.quick_log_queries import GetQuickLogsForRangeQuery
from worklogger.app.queries.settings_queries import GetSettingQuery
from worklogger.app.queries.work_log_queries import GetAllWorkLogsQuery
from worklogger.app.ports import AIRequest, AIResponse
from worklogger.app.use_cases.ai import AiChatHandler, BuildAiContextHandler
from worklogger.config.constants import (
    AI_PRIVACY_INCLUDE_CALENDAR_SETTING_KEY,
    AI_PRIVACY_INCLUDE_NOTES_SETTING_KEY,
    AI_PRIVACY_INCLUDE_QUICK_LOGS_SETTING_KEY,
)
from worklogger.domain.calendar.models import CalendarEvent
from worklogger.domain.notes.models import DailyNote
from worklogger.domain.notes.preferences import NoteSharing, note_sharing_key
from worklogger.domain.worklog.rules import aggregate_days
from worklogger.domain.quicklog.models import QuickLog
from worklogger.domain.shared.result import Result
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.worklog.models import WorkLog, EntryType
from worklogger.infrastructure.ai.external import OpenAICompatibleGateway


class FakeGateway:
    def __init__(self, text: str = "answer") -> None:
        self.text = text
        self.requests: list[AIRequest] = []

    def generate(self, request: AIRequest) -> Result[AIResponse]:
        self.requests.append(request)
        return Result.success(AIResponse(text=self.text, provider="fake"))


class FakeSettings:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = values or {}

    def handle(self, query: GetSettingQuery) -> Result[str | None]:
        return Result.success(self.values.get(query.key, query.default))


class FakeWorkLogs:
    def list_range(self, user_id, start, end):
        return Result.success(tuple(record for record in self.handle(GetAllWorkLogsQuery(user_id)).value if start <= record.day <= end))

    def handle(self, query: GetAllWorkLogsQuery) -> Result[tuple[WorkLog, ...]]:
        return Result.success(
            (
                WorkLog(
                    user_id=query.user_id,
                    day=date(2026, 5, 4),
                    start_time="09:00",
                    end_time="18:00",
                    break_hours=1.0,
                    note="private note",
                    entry_type=EntryType.NORMAL,
                ),
            )
        )


class FakeNotes:
    def list_range(self, user_id, start, end):
        return Result.success((DailyNote(user_id, start, "private note"),))

    def handle(self, query: GetDailyNoteQuery) -> Result[DailyNote]:
        return Result.success(
            DailyNote(
                user_id=query.user_id,
                day=query.day,
                content="private note",
            )
        )


class FakeQuickLogs:
    def handle(self, query: GetQuickLogsForRangeQuery) -> Result[tuple[QuickLog, ...]]:
        return Result.success(
            (
                QuickLog(
                    id=1,
                    user_id=query.user_id,
                    day=query.start_day,
                    start_time="10:00",
                    end_time="10:30",
                    description="Implement feature",
                ),
            )
        )


class FakeCalendar:
    def handle(
        self,
        query: GetCalendarEventsForRangeQuery,
    ) -> Result[tuple[CalendarEvent, ...]]:
        return Result.success(
            (
                CalendarEvent(
                    id=1,
                    user_id=query.user_id,
                    day=query.start_day,
                    start_time="11:00",
                    end_time="12:00",
                    summary="Private meeting title",
                ),
            )
        )


class FakeHttpResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "FakeHttpResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, _size: int) -> bytes:
        return self.payload


class AiUseCaseTests(unittest.TestCase):
    def test_chat_generation_uses_notes_language_without_using_the_interface_locale(self):
        gateway = FakeGateway()
        handler = AiChatHandler(gateway)
        source = "Work notes:\n\u30c6\u30b9\u30c8\u3084\u308b"
        for locale in ("en_US", "ja_JP", "zh_CN"):
            with self.subTest(locale=locale):
                self.assertTrue(handler.handle(SendAiChatMessageCommand(
                    1, "Generate a short report.", context=source, language=locale)).ok)
                messages = gateway.requests[-1].messages
                self.assertIn("use the language of those notes", messages[0]["content"])
                self.assertIn("only when the user explicitly requests", messages[0]["content"])
                self.assertIn(source, messages[-1]["content"])
                self.assertNotIn("Language:", messages[-1]["content"])
        handler.handle(SendAiChatMessageCommand(1, "Generate a short report.", context=source,
                                               output_language="en_US"))
        self.assertIn("Write in English, as explicitly requested", gateway.requests[-1].messages[0]["content"])

    def test_context_expands_time_periods_and_requires_memo_permission(self):
        day = date(2026, 5, 4)
        entries = (WorkLog(1, day, "09:00", "10:00", note="Planning", entry_type=EntryType.MEETING),
                   WorkLog(1, day, "10:00", "11:00", note="Learning", entry_type=EntryType.TRAINING))
        reader = Mock()
        reader.list_range.return_value = Result.success(aggregate_days(entries))
        settings = FakeSettings()
        handler = BuildAiContextHandler(work_logs_handler=reader, note_handler=FakeNotes(),
            quick_logs_handler=FakeQuickLogs(), calendar_events_handler=FakeCalendar(), settings_handler=settings)
        query = BuildAiContextQuery(1, day)
        content = handler.handle(query).value.content
        self.assertIn("09:00-10:00", content)
        self.assertIn("10:00-11:00", content)
        self.assertIn("Planning", content)
        self.assertIn("Learning", content)
        self.assertNotIn("private note", content)
        settings.values[note_sharing_key(day)] = NoteSharing(False, True).encode()
        self.assertIn("private note", handler.handle(query).value.content)
        settings.get_many = Mock(side_effect=lambda user_id, keys: Result.success(
            {key: settings.values.get(key) for key in keys}))
        self.assertIn("private note", handler.handle(query).value.content)
        self.assertEqual(settings.get_many.call_count, 2)
        del settings.get_many
        settings.values[AI_PRIVACY_INCLUDE_NOTES_SETTING_KEY] = "0"
        content = handler.handle(query).value.content
        self.assertNotIn("Planning", content)
        self.assertNotIn("private note", content)

    def test_context_reads_only_allowed_ranges_and_rejects_unavailable_settings(self) -> None:
        settings = FakeSettings({AI_PRIVACY_INCLUDE_NOTES_SETTING_KEY: "0",
                                 AI_PRIVACY_INCLUDE_CALENDAR_SETTING_KEY: "0",
                                 AI_PRIVACY_INCLUDE_QUICK_LOGS_SETTING_KEY: "0"})
        logs = Mock(wraps=FakeWorkLogs())
        notes, quick_logs, calendar = Mock(), Mock(), Mock()
        handler = BuildAiContextHandler(work_logs_handler=logs, note_handler=notes,
            quick_logs_handler=quick_logs, calendar_events_handler=calendar, settings_handler=settings)
        query = BuildAiContextQuery(1, date(2026, 5, 4), "weekly")
        self.assertTrue(handler.handle(query).ok)
        logs.list_range.assert_called_once_with(1, date(2026, 5, 3), date(2026, 5, 9))
        notes.list_range.assert_not_called()
        quick_logs.handle.assert_not_called()
        calendar.handle.assert_not_called()
        for day, end in ((date(2024, 2, 9), date(2024, 2, 29)), (date.max, date.max)):
            self.assertTrue(handler.handle(BuildAiContextQuery(1, day, "monthly")).ok)
            logs.list_range.assert_called_with(1, day.replace(day=1), end)
        count = logs.list_range.call_count
        settings.handle = Mock(return_value=Result.failure(InfrastructureError("settings_load_failed", "settings_load_failed")))
        self.assertFalse(handler.handle(query).ok)
        self.assertEqual(logs.list_range.call_count, count)
        self.assertEqual(AiChatHandler(FakeGateway()).handle(SendAiChatMessageCommand(1, "hello"),
            cancellation_token=type("Token", (), {"is_cancelled": True})()).error.code, "ai_chat_cancelled")

    def test_chat_handler_bounds_history_and_builds_request(self) -> None:
        gateway = FakeGateway("assistant reply")
        handler = AiChatHandler(gateway, max_history_messages=2)

        result = handler.handle(
            SendAiChatMessageCommand(
                user_id=1,
                message="What did I do?",
                history=(
                    {"role": "user", "content": "old"},
                    {"role": "assistant", "content": "old answer"},
                    {"role": "tool", "content": "ignored"},
                ),
                context="context line",
                language="en_US",
            )
        )

        self.assertTrue(result.ok)
        assert result.value is not None
        self.assertEqual(result.value.history[-1]["content"], "assistant reply")
        self.assertEqual(len(result.value.history), 2)
        self.assertIn("context line", gateway.requests[0].messages[-1]["content"])

    def test_context_builder_respects_privacy_settings(self) -> None:
        handler = BuildAiContextHandler(
            work_logs_handler=FakeWorkLogs(),
            note_handler=FakeNotes(),
            quick_logs_handler=FakeQuickLogs(),
            calendar_events_handler=FakeCalendar(),
            settings_handler=FakeSettings(
                {
                    AI_PRIVACY_INCLUDE_NOTES_SETTING_KEY: "0",
                    AI_PRIVACY_INCLUDE_CALENDAR_SETTING_KEY: "1",
                    AI_PRIVACY_INCLUDE_QUICK_LOGS_SETTING_KEY: "1",
                }
            ),
        )

        result = handler.handle(
            BuildAiContextQuery(
                user_id=1,
                selected_day=date(2026, 5, 4),
            )
        )

        self.assertTrue(result.ok)
        assert result.value is not None
        self.assertIn("Notes excluded by privacy settings.", result.value.content)
        self.assertIn("Implement feature", result.value.content)
        self.assertIn("Private meeting title", result.value.content)
        self.assertNotIn("- 2026-05-04: private note", result.value.content)

    def test_openai_compatible_gateway_posts_chat_completion(self) -> None:
        seen: dict[str, object] = {}

        def opener(request: object, timeout: float) -> FakeHttpResponse:
            seen["url"] = request.full_url
            seen["timeout"] = timeout
            seen["body"] = json.loads(request.data.decode("utf-8"))
            return FakeHttpResponse(
                {"choices": [{"message": {"content": "remote answer"}}]}
            )

        gateway = OpenAICompatibleGateway(
            api_key="secret",
            base_url="https://example.test/v1",
            opener=opener,
        )
        result = gateway.generate(
            AIRequest(
                messages=({"role": "user", "content": "hi"},),
                model="model-a",
                timeout_seconds=12,
            )
        )

        self.assertTrue(result.ok)
        assert result.value is not None
        self.assertEqual(result.value.text, "remote answer")
        self.assertEqual(seen["url"], "https://example.test/v1/chat/completions")
        self.assertEqual(seen["body"]["model"], "model-a")


if __name__ == "__main__":
    unittest.main()
