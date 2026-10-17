"""Privacy-aware context collection for AI requests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from worklogger.app.queries.ai_queries import BuildAiContextQuery
from worklogger.app.entry_labels import classification_label
from worklogger.app.queries.calendar_queries import GetCalendarEventsForRangeQuery
from worklogger.app.queries.quick_log_queries import GetQuickLogsForRangeQuery
from worklogger.app.settings import SettingsReader, read_setting_values
from worklogger.config.constants import (
    AI_PRIVACY_INCLUDE_CALENDAR_SETTING_KEY,
    AI_PRIVACY_INCLUDE_NOTES_SETTING_KEY,
    AI_PRIVACY_INCLUDE_QUICK_LOGS_SETTING_KEY,
    WEEK_START_MONDAY_SETTING_KEY,
)
from worklogger.domain.calendar.models import CalendarEvent
from worklogger.domain.notes.models import DailyNote
from worklogger.domain.notes.preferences import NoteSharing, note_sharing_key
from worklogger.domain.quicklog.models import QuickLog
from worklogger.domain.reporting.periods import period_for_day
from worklogger.domain.shared.errors import InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkLog


class WorkLogsReader(Protocol):
    def list_range(self, user_id: int, start: date, end: date) -> Result[tuple[WorkLog, ...]]:
        ...


class DailyNoteReader(Protocol):
    def list_range(self, user_id: int, start: date, end: date) -> Result[tuple[DailyNote, ...]]:
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


@dataclass(frozen=True)
class AiContextResult:
    content: str


class BuildAiContextHandler:
    def __init__(
        self,
        *,
        work_logs_handler: WorkLogsReader,
        note_handler: DailyNoteReader,
        quick_logs_handler: QuickLogsRangeReader,
        calendar_events_handler: CalendarEventsRangeReader,
        settings_handler: SettingsReader,
    ) -> None:
        self._work_logs_handler = work_logs_handler
        self._note_handler = note_handler
        self._quick_logs_handler = quick_logs_handler
        self._calendar_events_handler = calendar_events_handler
        self._settings_handler = settings_handler

    def handle(self, query: BuildAiContextQuery) -> Result[AiContextResult]:
        options_result = _context_options(self._settings_handler, query.user_id)
        if not options_result.ok or options_result.value is None:
            return Result.failure(options_result.error)
        options = options_result.value
        try:
            start_day, end_day = _context_range(query.selected_day, query.period_type, options["week_start_monday"])
        except ValueError as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        work_logs = self._work_logs_handler.list_range(query.user_id, start_day, end_day)
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
        approved_notes = []
        permissions = read_setting_values(self._settings_handler, query.user_id,
                                          {note_sharing_key(note.day): None for note in notes.value},
                                          error_code="ai_context_settings_failed")
        if not permissions.ok:
            return Result.failure(permissions.error)
        for note in notes.value:
            if NoteSharing.decode(permissions.value.get(note_sharing_key(note.day))).ai:
                approved_notes.append(note)
        quick_logs = self._quick_logs_handler.handle(
            GetQuickLogsForRangeQuery(query.user_id, start_day, end_day)
        ) if options["quick_logs"] else Result.success(())
        if not quick_logs.ok or quick_logs.value is None:
            return Result.failure(quick_logs.error or InfrastructureError("ai_context_failed", "ai_context_failed"))
        events = self._calendar_events_handler.handle(
            GetCalendarEventsForRangeQuery(query.user_id, start_day, end_day)
        ) if options["calendar"] else Result.success(())
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
            notes=tuple(approved_notes),
            quick_logs=quick_logs.value,
            events=events.value,
            include_notes=options["notes"],
            include_quick_logs=options["quick_logs"],
            include_calendar=options["calendar"],
        )
        if len(content) > 40_000:
            return Result.failure(ValidationError("ai_context_too_large", "ai_context_too_large"))
        return Result.success(AiContextResult(content=content))


def _context_range(selected_day: date, period_type: str, week_start_monday: bool = False) -> tuple[date, date]:
    scope = str(period_type or "daily").strip().lower()
    if scope not in {"daily", "weekly", "monthly"}:
        raise ValueError("unsupported_ai_context_period")
    period = period_for_day(scope, selected_day, week_start_monday)
    return period.start, period.end


def _context_options(handler: SettingsReader, user_id: int) -> Result[dict[str, bool]]:
    definitions = (
        ("notes", AI_PRIVACY_INCLUDE_NOTES_SETTING_KEY, "1"),
        ("calendar", AI_PRIVACY_INCLUDE_CALENDAR_SETTING_KEY, "1"),
        ("quick_logs", AI_PRIVACY_INCLUDE_QUICK_LOGS_SETTING_KEY, "1"),
        ("week_start_monday", WEEK_START_MONDAY_SETTING_KEY, "0"),
    )
    values = read_setting_values(handler, user_id, {key: default for _name, key, default in definitions},
                                 error_code="ai_context_settings_failed")
    if not values.ok:
        return Result.failure(values.error)
    return Result.success({name: str(values.value.get(key) or "").strip().lower() in {"1", "true", "yes", "on"}
                           for name, key, _default in definitions})


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
    return handler.list_range(user_id, start_day, end_day)


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
            for entry in record.entries or (record,):
                type_label = classification_label(entry.entry_type, entry.work_mode, str)
                category = getattr(entry.entry_type, "category", "")
                if category:
                    type_label += f" ({category})"
                lines.append(
                    f"- {entry.day.isoformat()} | {type_label} | "
                    f"{entry.start_time or '-'}-{entry.end_time or '-'} | "
                    f"break {entry.break_hours:.2f}h | worked {entry.worked_hours():.2f}h"
                    + (f" | project / work item: {_single_line(entry.context.label)}" if entry.context.label else "")
                    + (f" | content: {_single_line(entry.note)}" if include_notes and entry.note else "")
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
