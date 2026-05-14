"""AI-assisted text use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

from worklogger.app.commands.ai_commands import RewriteTextCommand, SendAiChatMessageCommand
from worklogger.app.queries.ai_queries import BuildAiContextQuery
from worklogger.app.queries.calendar_queries import GetCalendarEventsForRangeQuery
from worklogger.app.queries.note_queries import GetDailyNoteQuery
from worklogger.app.queries.quick_log_queries import GetQuickLogsForRangeQuery
from worklogger.app.queries.settings_queries import GetSettingQuery
from worklogger.app.queries.work_log_queries import GetAllWorkLogsQuery
from worklogger.app.ports import AIGateway, AIRequest
from worklogger.config.constants import (
    AI_PRIVACY_INCLUDE_CALENDAR_SETTING_KEY,
    AI_PRIVACY_INCLUDE_NOTES_SETTING_KEY,
    AI_PRIVACY_INCLUDE_QUICK_LOGS_SETTING_KEY,
)
from worklogger.domain.calendar.models import CalendarEvent
from worklogger.domain.notes.models import DailyNote
from worklogger.domain.quicklog.models import QuickLog
from worklogger.domain.shared.errors import CancellationError, InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkLog


class CancellationToken(Protocol):
    @property
    def is_cancelled(self) -> bool:
        ...


class WorkLogsReader(Protocol):
    def handle(self, query: GetAllWorkLogsQuery) -> Result[tuple[WorkLog, ...]]:
        ...


class DailyNoteReader(Protocol):
    def handle(self, query: GetDailyNoteQuery) -> Result[DailyNote]:
        ...


class QuickLogsRangeReader(Protocol):
    def handle(self, query: GetQuickLogsForRangeQuery) -> Result[tuple[QuickLog, ...]]:
        ...


class CalendarEventsRangeReader(Protocol):
    def handle(
        self,
        query: GetCalendarEventsForRangeQuery,
    ) -> Result[tuple[CalendarEvent, ...]]:
        ...


class SettingReader(Protocol):
    def handle(self, query: GetSettingQuery) -> Result[str | None]:
        ...


@dataclass(frozen=True)
class RewriteTextResult:
    content: str


@dataclass(frozen=True)
class AiChatResult:
    reply: str
    history: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class AiContextResult:
    content: str


class RewriteTextHandler:
    def __init__(
        self,
        gateway: AIGateway | None = None,
        *,
        model: str = "rewrite-placeholder",
        timeout_seconds: float = 30.0,
    ) -> None:
        self._gateway = gateway
        self._model = model
        self._timeout_seconds = timeout_seconds

    def handle(
        self,
        command: RewriteTextCommand,
        cancellation_token: CancellationToken | None = None,
    ) -> Result[RewriteTextResult]:
        if _cancelled(cancellation_token):
            return Result.failure(_cancelled_error())
        content = str(command.content or "").strip()
        if not content:
            return Result.failure(ValidationError("rewrite_content_required", "rewrite_content_required"))
        if self._gateway is None:
            return Result.failure(
                InfrastructureError(
                    "ai_rewrite_not_configured",
                    "ai_rewrite_not_configured",
                )
            )
        try:
            response = self._gateway.generate(
                AIRequest(
                    messages=_rewrite_messages(
                        content=content,
                        context=command.context,
                        language=command.language,
                    ),
                    model=self._model,
                    timeout_seconds=self._timeout_seconds,
                )
            )
        except Exception as exc:
            return Result.failure(
                InfrastructureError(
                    "ai_rewrite_failed",
                    "ai_rewrite_failed",
                    {"reason": str(exc)},
                )
            )
        if _cancelled(cancellation_token):
            return Result.failure(_cancelled_error())
        if not response.ok or response.value is None:
            return Result.failure(response.error or InfrastructureError("ai_rewrite_failed", "ai_rewrite_failed"))
        rewritten = response.value.text.strip()
        if not rewritten:
            return Result.failure(InfrastructureError("ai_rewrite_empty", "ai_rewrite_empty"))
        return Result.success(RewriteTextResult(rewritten))


def _rewrite_messages(
    *,
    content: str,
    context: str,
    language: str,
) -> tuple[dict[str, str], ...]:
    normalized_context = str(context or "note").strip() or "note"
    normalized_language = str(language or "en_US").strip() or "en_US"
    return (
        {
            "role": "system",
            "content": (
                "Rewrite the user's work note or report for clarity while preserving facts, "
                "dates, durations, task names, and meaning. Return only the rewritten text."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Context: {normalized_context}\n"
                f"Language: {normalized_language}\n\n"
                f"{content}"
            ),
        },
    )


class AiChatHandler:
    def __init__(
        self,
        gateway: AIGateway | None = None,
        *,
        model: str = "chat-placeholder",
        timeout_seconds: float = 60.0,
        max_history_messages: int = 12,
    ) -> None:
        self._gateway = gateway
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_history_messages = max(0, int(max_history_messages))

    def handle(
        self,
        command: SendAiChatMessageCommand,
        cancellation_token: CancellationToken | None = None,
    ) -> Result[AiChatResult]:
        if _cancelled(cancellation_token):
            return Result.failure(_cancelled_error())
        message = str(command.message or "").strip()
        if not message:
            return Result.failure(ValidationError("ai_chat_message_required", "ai_chat_message_required"))
        if self._gateway is None:
            return Result.failure(
                InfrastructureError("ai_chat_not_configured", "ai_chat_not_configured")
            )
        history = _bounded_history(command.history, self._max_history_messages)
        request_messages = (
            {
                "role": "system",
                "content": (
                    "You are WorkLogger AI Assist. Help with work log analysis, notes, "
                    "and reports. Preserve facts and avoid inventing records."
                ),
            },
            *history,
            {
                "role": "user",
                "content": _chat_user_content(
                    message=message,
                    context=command.context,
                    language=command.language,
                ),
            },
        )
        try:
            response = self._gateway.generate(
                AIRequest(
                    messages=request_messages,
                    model=self._model,
                    timeout_seconds=self._timeout_seconds,
                )
            )
        except Exception as exc:
            return Result.failure(
                InfrastructureError(
                    "ai_chat_failed",
                    "ai_chat_failed",
                    {"reason": str(exc)},
                )
            )
        if _cancelled(cancellation_token):
            return Result.failure(_cancelled_error())
        if not response.ok or response.value is None:
            return Result.failure(response.error or InfrastructureError("ai_chat_failed", "ai_chat_failed"))
        reply = response.value.text.strip()
        if not reply:
            return Result.failure(InfrastructureError("ai_chat_empty", "ai_chat_empty"))
        next_history = _bounded_history(
            (
                *history,
                {"role": "user", "content": message},
                {"role": "assistant", "content": reply},
            ),
            self._max_history_messages,
        )
        return Result.success(AiChatResult(reply=reply, history=next_history))


class BuildAiContextHandler:
    def __init__(
        self,
        *,
        work_logs_handler: WorkLogsReader,
        note_handler: DailyNoteReader,
        quick_logs_handler: QuickLogsRangeReader,
        calendar_events_handler: CalendarEventsRangeReader,
        settings_handler: SettingReader,
    ) -> None:
        self._work_logs_handler = work_logs_handler
        self._note_handler = note_handler
        self._quick_logs_handler = quick_logs_handler
        self._calendar_events_handler = calendar_events_handler
        self._settings_handler = settings_handler

    def handle(self, query: BuildAiContextQuery) -> Result[AiContextResult]:
        try:
            start_day, end_day = _context_range(query.selected_day, query.period_type)
        except ValueError as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        options = _context_options(self._settings_handler, query.user_id)
        work_logs = self._work_logs_handler.handle(GetAllWorkLogsQuery(query.user_id))
        if not work_logs.ok or work_logs.value is None:
            return Result.failure(work_logs.error or InfrastructureError("ai_context_failed", "ai_context_failed"))
        notes = _notes_for_range(
            self._note_handler,
            query.user_id,
            start_day,
            end_day,
            include_notes=options["notes"],
        )
        if not notes.ok or notes.value is None:
            return Result.failure(notes.error or InfrastructureError("ai_context_failed", "ai_context_failed"))
        quick_logs = self._quick_logs_handler.handle(
            GetQuickLogsForRangeQuery(query.user_id, start_day, end_day)
        )
        if not quick_logs.ok or quick_logs.value is None:
            return Result.failure(quick_logs.error or InfrastructureError("ai_context_failed", "ai_context_failed"))
        events = self._calendar_events_handler.handle(
            GetCalendarEventsForRangeQuery(query.user_id, start_day, end_day)
        )
        if not events.ok or events.value is None:
            return Result.failure(events.error or InfrastructureError("ai_context_failed", "ai_context_failed"))
        filtered_logs = tuple(
            record
            for record in work_logs.value
            if start_day <= record.day <= end_day
        )
        content = _format_context(
            period_type=query.period_type,
            start_day=start_day,
            end_day=end_day,
            work_logs=filtered_logs,
            notes=notes.value,
            quick_logs=quick_logs.value,
            events=events.value,
            include_notes=options["notes"],
            include_quick_logs=options["quick_logs"],
            include_calendar=options["calendar"],
        )
        return Result.success(AiContextResult(content=content))


def _bounded_history(
    history: tuple[object, ...],
    max_messages: int,
) -> tuple[dict[str, str], ...]:
    clean: list[dict[str, str]] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            clean.append({"role": role, "content": content})
    return tuple(clean[-max_messages:]) if max_messages else ()


def _chat_user_content(
    *,
    message: str,
    context: str,
    language: str,
) -> str:
    context_text = str(context or "").strip()
    language_text = str(language or "en_US").strip() or "en_US"
    if context_text:
        return f"Language: {language_text}\nContext:\n{context_text}\n\nUser:\n{message}"
    return f"Language: {language_text}\n\nUser:\n{message}"


def _context_range(selected_day: date, period_type: str) -> tuple[date, date]:
    scope = str(period_type or "daily").strip().lower()
    if scope == "daily":
        return selected_day, selected_day
    if scope == "weekly":
        start_day = selected_day - timedelta(days=selected_day.weekday())
        return start_day, start_day + timedelta(days=6)
    if scope == "monthly":
        start_day = selected_day.replace(day=1)
        if start_day.month == 12:
            next_month = start_day.replace(year=start_day.year + 1, month=1)
        else:
            next_month = start_day.replace(month=start_day.month + 1)
        return start_day, next_month - timedelta(days=1)
    raise ValueError("unsupported_ai_context_period")


def _context_options(handler: SettingReader, user_id: int) -> dict[str, bool]:
    return {
        "notes": _setting_bool(handler, user_id, AI_PRIVACY_INCLUDE_NOTES_SETTING_KEY, True),
        "calendar": _setting_bool(handler, user_id, AI_PRIVACY_INCLUDE_CALENDAR_SETTING_KEY, True),
        "quick_logs": _setting_bool(handler, user_id, AI_PRIVACY_INCLUDE_QUICK_LOGS_SETTING_KEY, True),
    }


def _setting_bool(handler: SettingReader, user_id: int, key: str, default: bool) -> bool:
    result = handler.handle(GetSettingQuery(user_id, key, "1" if default else "0"))
    if not result.ok:
        return default
    return str(result.value or "").strip().lower() in {"1", "true", "yes", "on"}


def _notes_for_range(
    handler: DailyNoteReader,
    user_id: int,
    start_day: date,
    end_day: date,
    *,
    include_notes: bool,
) -> Result[tuple[DailyNote, ...]]:
    if not include_notes:
        return Result.success(())
    notes: list[DailyNote] = []
    day = start_day
    while day <= end_day:
        result = handler.handle(GetDailyNoteQuery(user_id, day))
        if not result.ok or result.value is None:
            return Result.failure(result.error or InfrastructureError("ai_context_failed", "ai_context_failed"))
        if result.value.content.strip():
            notes.append(result.value)
        day += timedelta(days=1)
    return Result.success(tuple(notes))


def _format_context(
    *,
    period_type: str,
    start_day: date,
    end_day: date,
    work_logs: tuple[WorkLog, ...],
    notes: tuple[DailyNote, ...],
    quick_logs: tuple[QuickLog, ...],
    events: tuple[CalendarEvent, ...],
    include_notes: bool,
    include_quick_logs: bool,
    include_calendar: bool,
) -> str:
    lines = [
        "# WorkLogger Context",
        f"Period: {period_type}",
        f"Range: {start_day.isoformat()} to {end_day.isoformat()}",
        "",
        "## Work Logs",
    ]
    if work_logs:
        for record in sorted(work_logs, key=lambda item: item.day):
            lines.append(
                "- "
                f"{record.day.isoformat()} | {record.work_type.value} | "
                f"{record.start_time or '-'}-{record.end_time or '-'} | "
                f"break {record.break_hours:.2f}h | "
                f"worked {record.worked_hours():.2f}h"
            )
    else:
        lines.append("No work logs found.")
    lines.extend(["", "## Notes"])
    if include_notes:
        if notes:
            for note in sorted(notes, key=lambda item: item.day):
                lines.append(f"- {note.day.isoformat()}: {_single_line(note.content)}")
        else:
            lines.append("No notes found.")
    else:
        lines.append("Notes excluded by privacy settings.")
    lines.extend(["", "## Quick Logs"])
    if include_quick_logs:
        if quick_logs:
            for log in sorted(quick_logs, key=lambda item: (item.day, item.start_time or "")):
                span = _span(log.start_time, log.end_time)
                lines.append(f"- {log.day.isoformat()} {span}{_single_line(log.description)}")
        else:
            lines.append("No quick logs found.")
    else:
        lines.append("Quick logs excluded by privacy settings.")
    lines.extend(["", "## Calendar"])
    if include_calendar:
        if events:
            for event in sorted(events, key=lambda item: (item.day, item.start_time or "")):
                summary = _single_line(event.summary)
                when = "all day" if event.all_day else _span(event.start_time, event.end_time).strip()
                lines.append(f"- {event.day.isoformat()} {when}: {summary}")
        else:
            lines.append("No calendar events found.")
    else:
        lines.append("Calendar excluded by privacy settings.")
    return "\n".join(lines).strip()


def _single_line(value: str) -> str:
    return " ".join(str(value or "").split())


def _span(start: str | None, end: str | None) -> str:
    if start and end:
        return f"{start}-{end}: "
    if start:
        return f"{start}: "
    return ""


def _cancelled(cancellation_token: CancellationToken | None) -> bool:
    value = getattr(cancellation_token, "is_cancelled", False)
    return bool(value() if callable(value) else value)


def _cancelled_error() -> CancellationError:
    return CancellationError("ai_rewrite_cancelled", "ai_rewrite_cancelled")
