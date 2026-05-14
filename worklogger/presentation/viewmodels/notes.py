"""Notes presentation ViewModel."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from worklogger.app.commands.ai_commands import RewriteTextCommand
from worklogger.app.commands.note_commands import SaveDailyNoteCommand
from worklogger.app.commands.report_commands import (
    ResetReportTemplateCommand,
    SaveReportTemplateCommand,
)
from worklogger.app.queries.calendar_queries import GetCalendarEventsForDayQuery
from worklogger.app.queries.note_queries import GetDailyNoteQuery
from worklogger.app.queries.quick_log_queries import GetQuickLogsForDayQuery
from worklogger.app.use_cases.ai import RewriteTextResult
from worklogger.domain.calendar.models import CalendarEvent
from worklogger.domain.notes.models import DailyNote
from worklogger.domain.quicklog.models import QuickLog
from worklogger.domain.reporting.templates import ReportTemplate, render_template
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result


class GetDailyNoteHandlerProtocol(Protocol):
    def handle(self, query: GetDailyNoteQuery) -> Result[DailyNote]:
        ...


class SaveDailyNoteHandlerProtocol(Protocol):
    def handle(self, command: SaveDailyNoteCommand) -> Result[DailyNote]:
        ...


class QuickLogsForDayHandlerProtocol(Protocol):
    def handle(self, query: GetQuickLogsForDayQuery) -> Result[tuple[QuickLog, ...]]:
        ...


class CalendarEventsForDayHandlerProtocol(Protocol):
    def handle(
        self,
        query: GetCalendarEventsForDayQuery,
    ) -> Result[tuple[CalendarEvent, ...]]:
        ...


class TemplateProviderProtocol(Protocol):
    def get_template(
        self,
        language: str,
        template_type: str,
        user_id: int | None = None,
    ) -> Result[str]:
        ...


class SaveTemplateHandlerProtocol(Protocol):
    def handle(self, command: SaveReportTemplateCommand) -> Result[ReportTemplate]:
        ...


class ResetTemplateHandlerProtocol(Protocol):
    def handle(self, command: ResetReportTemplateCommand) -> Result[None]:
        ...


class MarkdownExportServiceProtocol(Protocol):
    def export_markdown(self, destination: Path, content: str) -> Result[Path]:
        ...


class RewriteTextHandlerProtocol(Protocol):
    def handle(self, command: RewriteTextCommand) -> Result[RewriteTextResult]:
        ...


@dataclass(frozen=True)
class NoteEditorState:
    user_id: int
    day: date
    content: str
    quick_logs: tuple[QuickLog, ...] = ()
    calendar_events: tuple[CalendarEvent, ...] = ()


class NoteEditorViewModel:
    def __init__(
        self,
        *,
        user_id: int,
        get_note_handler: GetDailyNoteHandlerProtocol,
        save_note_handler: SaveDailyNoteHandlerProtocol,
        quick_logs_handler: QuickLogsForDayHandlerProtocol,
        calendar_events_handler: CalendarEventsForDayHandlerProtocol,
        templates: TemplateProviderProtocol,
        save_template_handler: SaveTemplateHandlerProtocol,
        reset_template_handler: ResetTemplateHandlerProtocol,
        markdown_exporter: MarkdownExportServiceProtocol,
        rewrite_handler: RewriteTextHandlerProtocol,
        language: str = "en_US",
    ) -> None:
        self._user_id = user_id
        self._get_note_handler = get_note_handler
        self._save_note_handler = save_note_handler
        self._quick_logs_handler = quick_logs_handler
        self._calendar_events_handler = calendar_events_handler
        self._templates = templates
        self._save_template_handler = save_template_handler
        self._reset_template_handler = reset_template_handler
        self._markdown_exporter = markdown_exporter
        self._rewrite_handler = rewrite_handler
        self._language = language

    def load(self, day: date) -> Result[NoteEditorState]:
        note = self._get_note_handler.handle(GetDailyNoteQuery(self._user_id, day))
        if not note.ok or note.value is None:
            return Result.failure(note.error or _validation("note_load_failed"))
        quick_logs = self._quick_logs_handler.handle(
            GetQuickLogsForDayQuery(self._user_id, day)
        )
        if not quick_logs.ok or quick_logs.value is None:
            return Result.failure(quick_logs.error or _validation("quick_log_load_failed"))
        events = self._calendar_events_handler.handle(
            GetCalendarEventsForDayQuery(self._user_id, day)
        )
        if not events.ok or events.value is None:
            return Result.failure(events.error or _validation("calendar_load_failed"))
        return Result.success(
            NoteEditorState(
                user_id=self._user_id,
                day=day,
                content=note.value.content,
                quick_logs=quick_logs.value,
                calendar_events=events.value,
            )
        )

    def save(self, day: date, content: str) -> Result[NoteEditorState]:
        saved = self._save_note_handler.handle(
            SaveDailyNoteCommand(
                user_id=self._user_id,
                day=day,
                content=content,
            )
        )
        if not saved.ok or saved.value is None:
            return Result.failure(saved.error or _validation("note_save_failed"))
        loaded = self.load(day)
        if loaded.ok:
            return loaded
        return Result.success(
            NoteEditorState(
                user_id=self._user_id,
                day=day,
                content=saved.value.content,
            )
        )

    def insert_quick_logs(self, state: NoteEditorState) -> str:
        block = _quick_log_block(state.quick_logs)
        if not block:
            return state.content
        existing = state.content.rstrip()
        joiner = "\n\n" if existing else ""
        return f"{existing}{joiner}## Work Log\n{block}".strip()

    def apply_template(self, state: NoteEditorState) -> Result[str]:
        template = self._templates.get_template(
            self._language,
            "daily",
            user_id=self._user_id,
        )
        if not template.ok:
            return Result.failure(template.error or _validation("template_load_failed"))
        return Result.success(
            render_template(
                template.value or "",
                {
                    "date": state.day.isoformat(),
                    "task_list": "- ",
                    "calendar_events": _event_block(state.calendar_events),
                    "quick_logs": _quick_log_block(state.quick_logs),
                    "total_hours": "",
                    "overtime_hours": "",
                    "issues": "- ",
                    "next_plan": "- ",
                },
            )
        )

    def save_template(self, content: str) -> Result[ReportTemplate]:
        return self._save_template_handler.handle(
            SaveReportTemplateCommand(
                user_id=self._user_id,
                language=self._language,
                template_type="daily",
                content=content,
            )
        )

    def reset_template(self) -> Result[None]:
        return self._reset_template_handler.handle(
            ResetReportTemplateCommand(
                user_id=self._user_id,
                language=self._language,
                template_type="daily",
            )
        )

    def export_markdown(self, destination: Path, content: str) -> Result[Path]:
        return self._markdown_exporter.export_markdown(destination, content)

    def rewrite(self, content: str) -> Result[str]:
        result = self._rewrite_handler.handle(
            RewriteTextCommand(
                user_id=self._user_id,
                content=content,
                context="daily_note",
                language=self._language,
            )
        )
        if not result.ok or result.value is None:
            return Result.failure(result.error or _validation("rewrite_failed"))
        return Result.success(result.value.content)


def _quick_log_block(quick_logs: tuple[QuickLog, ...]) -> str:
    lines: list[str] = []
    for quick_log in quick_logs:
        time_text = _time_range(quick_log.start_time, quick_log.end_time)
        prefix = f"{time_text}: " if time_text else ""
        lines.append(f"- {prefix}{quick_log.description}")
    return "\n".join(lines)


def _event_block(events: tuple[CalendarEvent, ...]) -> str:
    lines: list[str] = []
    for event in events:
        time_text = "All day" if event.all_day else _time_range(event.start_time, event.end_time)
        prefix = f"{time_text}: " if time_text else ""
        lines.append(f"- {prefix}{event.summary}")
    return "\n".join(lines) if lines else "- "


def _time_range(start_time: str | None, end_time: str | None) -> str:
    start = str(start_time or "").strip()
    end = str(end_time or "").strip()
    if start and end:
        return f"{start}-{end}"
    return start or end


def _validation(code: str) -> ValidationError:
    return ValidationError(code, code)
