from __future__ import annotations

from datetime import date
import json
import unittest

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
from worklogger.domain.quicklog.models import QuickLog
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkLog, WorkType
from worklogger.infrastructure.ai.external import OpenAICompatibleGateway
from worklogger.infrastructure.ai.router import RoutingAIGateway


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
                    work_type=WorkType.NORMAL,
                ),
            )
        )


class FakeNotes:
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

    def test_routing_gateway_uses_secondary_and_falls_back_to_primary(self) -> None:
        primary = FakeGateway("primary")
        secondary = FakeGateway("secondary")
        routed = RoutingAIGateway(primary=primary, secondary=secondary)

        secondary_result = routed.generate(
            AIRequest(
                messages=({"role": "user", "content": "hi"},),
                model="secondary:model-b",
                timeout_seconds=1,
            )
        )
        fallback_result = RoutingAIGateway(primary=primary).generate(
            AIRequest(
                messages=({"role": "user", "content": "hi"},),
                model="secondary:model-c",
                timeout_seconds=1,
            )
        )

        self.assertEqual(secondary_result.value.text if secondary_result.value else "", "secondary")
        self.assertEqual(secondary.requests[0].model, "model-b")
        self.assertEqual(fallback_result.value.text if fallback_result.value else "", "primary")
        self.assertEqual(primary.requests[-1].model, "model-c")


if __name__ == "__main__":
    unittest.main()
