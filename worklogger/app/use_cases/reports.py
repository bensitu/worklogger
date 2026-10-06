"""Report use cases."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from functools import partial
from datetime import date
import math
from typing import Protocol

from worklogger.app.commands.report_commands import (
    DeleteReportCommand,
    GenerateReportCommand,
    ResetReportTemplateCommand,
    SaveReportCommand,
    SaveReportTemplateCommand,
)
from worklogger.app.queries.report_queries import (
    GetReportForPeriodQuery,
    GetReportTemplateQuery,
    ListReportsQuery,
    ListReportTemplatesQuery,
)
from worklogger.domain.calendar.models import CalendarEvent
from worklogger.domain.calendar.repositories import CalendarEventRepository
from worklogger.domain.notes.repositories import DailyNoteRepository
from worklogger.domain.quicklog.models import QuickLog
from worklogger.domain.quicklog.repositories import QuickLogRepository
from worklogger.domain.reporting.models import Report
from worklogger.domain.reporting.periods import normalize_report_type, validate_report_period
from worklogger.domain.reporting.repositories import ReportRepository, ReportTemplateRepository
from worklogger.domain.reporting.templates import (
    ReportTemplate,
    normalize_template_language,
    normalize_template_type,
    render_template,
)
from worklogger.domain.shared.errors import ConflictError, InfrastructureError, NotFoundError, ValidationError
from worklogger.domain.shared.dates import time_range_label
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkLog
from worklogger.domain.worklog.repositories import WorkLogRepository


class TemplateProvider(Protocol):
    def get_template(
        self,
        language: str,
        template_type: str,
        user_id: int | None = None,
    ) -> Result[str]:
        ...


@dataclass(frozen=True)
class GeneratedReport:
    report_type: str
    period_start: date
    period_end: date
    content: str


class SaveReportHandler:
    def __init__(self, repository: ReportRepository) -> None:
        self._repository = repository

    def handle(self, command: SaveReportCommand) -> Result[Report]:
        try:
            period = validate_report_period(
                command.report_type,
                command.period_start,
                command.period_end,
            )
            if not isinstance(command.content, str) or not command.content.strip():
                raise ValueError("report_content_required")
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        report = Report(
            id=command.report_id,
            user_id=command.user_id,
            report_type=period.report_type,
            period_start=period.start,
            period_end=period.end,
            content=command.content,
        )
        try:
            return Result.success(self._repository.save(report))
        except ValueError as exc:
            if str(exc) == "report_not_found":
                return Result.failure(NotFoundError("report_not_found", "report_not_found"))
            return Result.failure(ValidationError(str(exc), str(exc)))
        except Exception:
            return Result.failure(InfrastructureError("report_save_failed", "report_save_failed"))


class DeleteReportHandler:
    def __init__(self, repository: ReportRepository) -> None:
        self._repository = repository

    def handle(self, command: DeleteReportCommand) -> Result[None]:
        try:
            if command.expected_content is None:
                self._repository.remove(command.user_id, command.report_id)
            else:
                self._repository.remove(command.user_id, command.report_id, expected_content=command.expected_content)
            return Result.success(None)
        except ValueError as exc:
            if str(exc) == "report_not_found":
                return Result.failure(NotFoundError("report_not_found", "report_not_found"))
            if str(exc) == "report_conflict":
                return Result.failure(ConflictError("report_conflict", "report_conflict"))
            return Result.failure(InfrastructureError("report_delete_failed", "report_delete_failed"))
        except Exception:
            return Result.failure(InfrastructureError("report_delete_failed", "report_delete_failed"))


class GetReportForPeriodHandler:
    def __init__(self, repository: ReportRepository) -> None:
        self._repository = repository

    def handle(self, query: GetReportForPeriodQuery) -> Result[Report | None]:
        try:
            period = validate_report_period(
                query.report_type,
                query.period_start,
                query.period_end,
            )
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        return Result.success(
            self._repository.get_for_period(
                query.user_id,
                period.report_type,
                period.start,
                period.end,
            )
        )


class ListReportsHandler:
    def __init__(self, repository: ReportRepository) -> None:
        self._repository = repository

    def handle(self, query: ListReportsQuery) -> Result[tuple[Report, ...]]:
        try:
            report_type = normalize_report_type(query.report_type)
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        return Result.success(self._repository.list_by_type(query.user_id, report_type))


class SaveReportTemplateHandler:
    def __init__(self, repository: ReportTemplateRepository) -> None:
        self._repository = repository

    def handle(self, command: SaveReportTemplateCommand) -> Result[ReportTemplate]:
        try:
            template_type = normalize_template_type(command.template_type)
            language = normalize_template_language(command.language)
            if not isinstance(command.content, str) or not command.content.strip():
                raise ValueError("template_content_required")
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        template = ReportTemplate(
            id=None,
            user_id=command.user_id,
            language=language,
            template_type=template_type,
            content=command.content,
        )
        return Result.success(self._repository.save(template))


class ResetReportTemplateHandler:
    def __init__(self, repository: ReportTemplateRepository) -> None:
        self._repository = repository

    def handle(self, command: ResetReportTemplateCommand) -> Result[None]:
        try:
            template_type = normalize_template_type(command.template_type)
            language = normalize_template_language(command.language)
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        self._repository.remove(command.user_id, language, template_type)
        return Result.success(None)


class GetReportTemplateHandler:
    def __init__(self, repository: ReportTemplateRepository) -> None:
        self._repository = repository

    def handle(self, query: GetReportTemplateQuery) -> Result[ReportTemplate | None]:
        try:
            template_type = normalize_template_type(query.template_type)
            language = normalize_template_language(query.language)
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        return Result.success(self._repository.get(query.user_id, language, template_type))


class ListReportTemplatesHandler:
    def __init__(self, repository: ReportTemplateRepository) -> None:
        self._repository = repository

    def handle(self, query: ListReportTemplatesQuery) -> Result[tuple[ReportTemplate, ...]]:
        language = (
            normalize_template_language(query.language)
            if query.language is not None
            else None
        )
        return Result.success(self._repository.list_for_user(query.user_id, language))


class GenerateReportHandler:
    def __init__(
        self,
        *,
        work_logs: WorkLogRepository,
        quick_logs: QuickLogRepository,
        calendar_events: CalendarEventRepository,
        templates: TemplateProvider,
        notes: DailyNoteRepository | None = None,
        translator: Callable[..., str] | None = None,
    ) -> None:
        self._work_logs = work_logs
        self._quick_logs = quick_logs
        self._calendar_events = calendar_events
        self._templates = templates
        self._notes = notes
        self._translator = translator or (lambda message, **kwargs: message)

    def handle(self, command: GenerateReportCommand) -> Result[GeneratedReport]:
        try:
            period = validate_report_period(
                command.report_type,
                command.period_start,
                command.period_end,
            )
            standard_hours = float(command.standard_work_hours)
            if not math.isfinite(standard_hours) or not 1 <= standard_hours <= 24:
                raise ValueError("standard_work_hours_invalid")
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))

        try:
            work_logs = self._work_logs.list_range(command.user_id, period.start, period.end)
            if self._notes is not None:
                notes = self._notes.list_range(command.user_id, period.start, period.end)
                recorded_notes = {(entry.day, entry.note) for record in work_logs for entry in (record.entries or (record,))}
                work_logs += tuple(WorkLog(command.user_id, note.day, note=note.content)
                                   for note in notes if note.content and (note.day, note.content) not in recorded_notes)
            quick_logs = self._quick_logs.list_for_range(command.user_id, period.start, period.end)
            events = self._calendar_events.list_for_range(command.user_id, period.start, period.end)
            template = self._templates.get_template(
                command.language, period.report_type, user_id=command.user_id,
            )
        except Exception:
            return Result.failure(InfrastructureError("report_load_failed", "report_load_failed"))
        translate = partial(self._translator, language=command.language)
        if not template.ok or not template.value:
            content = _fallback_report(period.report_type, period.start, period.end, translate)
        else:
            content = render_template(
                template.value,
                _template_values(
                    report_type=period.report_type,
                    start=period.start,
                    end=period.end,
                    work_logs=work_logs,
                    quick_logs=quick_logs,
                    events=events,
                    standard_hours=standard_hours,
                    translate=translate,
                ),
            )
        return Result.success(
            GeneratedReport(
                report_type=period.report_type,
                period_start=period.start,
                period_end=period.end,
                content=content,
            )
        )


def _template_values(
    *,
    report_type: str,
    start: date,
    end: date,
    work_logs: tuple[WorkLog, ...],
    quick_logs: tuple[QuickLog, ...],
    events: tuple[CalendarEvent, ...],
    standard_hours: float,
    translate: Callable[[str], str],
) -> dict[str, object]:
    total = sum(work_log.worked_hours() for work_log in work_logs if not work_log.is_leave)
    overtime = sum(
        max(work_log.worked_hours() - standard_hours, 0.0)
        for work_log in work_logs
        if not work_log.is_leave
    )
    return {
        "date": start.isoformat(),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "date_range": f"{start.isoformat()} - {end.isoformat()}",
        "year": start.year,
        "month": f"{start.month:02d}" if report_type == "monthly" else start.month,
        "task_list": _work_log_lines(work_logs, standard_hours, translate),
        "calendar_events": _event_lines(events, translate),
        "quick_logs": _quick_log_lines(quick_logs),
        "total_hours": f"{total:.1f}",
        "overtime_hours": f"{overtime:.1f}",
        "issues": "- ",
        "next_plan": "- ",
    }


def _work_log_lines(work_logs: tuple[WorkLog, ...], standard_hours: float, _: Callable[[str], str]) -> str:
    if not work_logs:
        return "- " + _("No notes recorded for this period.")
    lines: list[str] = []
    for work_log in sorted(work_logs, key=lambda item: item.day):
        if work_log.is_note_only:
            lines.append(_list_item(f"{work_log.day.isoformat()} - {work_log.note}"))
            continue
        if work_log.entries:
            total = work_log.worked_hours()
            lines.append(_list_item(f"{work_log.day.isoformat()}: {total:.1f}h"))
            labels = {"normal": _("Normal"), "remote": _("Remote"), "business_trip": _("Business trip"),
                      "meeting": _("Meeting"), "training": _("Training"), "break": _("Break"),
                      "other": _("Other"),
                      "paid_leave": _("Paid leave"), "comp_leave": _("Compensatory leave"), "sick_leave": _("Sick leave")}
            for entry in work_log.entries:
                period = time_range_label(entry.start_time, entry.end_time)
                description = f"{period} [{labels[entry.work_type.value]}]"
                if entry.note:
                    description += f" - {entry.note}"
                lines.append("  " + _list_item(description))
            continue
        if work_log.is_leave:
            labels = {"paid_leave": _("Paid leave"), "comp_leave": _("Compensatory leave"), "sick_leave": _("Sick leave")}
            suffix = f" [{labels[work_log.work_type.value]}]"
            note = f" - {work_log.note}" if work_log.note else ""
            lines.append(_list_item(f"{work_log.day.isoformat()}{suffix}{note}"))
            continue
        hours = work_log.worked_hours()
        overtime = max(hours - standard_hours, 0.0)
        parts = [f"{work_log.day.isoformat()}: {hours:.1f}h"]
        if overtime > 0:
            parts.append(_("Overtime") + f" +{overtime:.1f}h")
        if work_log.is_overnight:
            parts.append(_("Overnight"))
        if work_log.note:
            parts.append(work_log.note)
        lines.append(_list_item("  ".join(parts)))
    return "\n".join(lines)


def _quick_log_lines(quick_logs: tuple[QuickLog, ...]) -> str:
    if not quick_logs:
        return "- "
    lines: list[str] = []
    for quick_log in sorted(quick_logs, key=lambda item: (item.day, item.start_time, item.id or 0)):
        time_text = time_range_label(quick_log.start_time, quick_log.end_time)
        prefix = f"{quick_log.day.isoformat()} {time_text}".strip()
        lines.append(_list_item(f"{prefix}: {quick_log.description}"))
    return "\n".join(lines)


def _event_lines(events: tuple[CalendarEvent, ...], _: Callable[[str], str]) -> str:
    if not events:
        return "- "
    lines: list[str] = []
    for event in sorted(events, key=lambda item: (item.day, item.start_time or "", item.summary)):
        time_text = _("All day") if event.all_day else time_range_label(event.start_time, event.end_time)
        prefix = f"{event.day.isoformat()} {time_text}".strip()
        lines.append(_list_item(f"{prefix}: {event.summary}"))
    return "\n".join(lines)


def _list_item(content: str) -> str:
    return "- " + content.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\n  ")


def _fallback_report(report_type: str, start: date, end: date, _: Callable[[str], str]) -> str:
    if report_type == "daily":
        title = _("Daily Report")
    elif report_type == "weekly":
        title = _("Weekly Report")
    else:
        title = _("Monthly Report")
    return f"# {title}  {start.isoformat()} - {end.isoformat()}\n\n- "
