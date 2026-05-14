"""Report use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
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
from worklogger.domain.shared.errors import ValidationError
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
            id=None,
            user_id=command.user_id,
            report_type=period.report_type,
            period_start=period.start,
            period_end=period.end,
            content=command.content,
        )
        return Result.success(self._repository.save(report))


class DeleteReportHandler:
    def __init__(self, repository: ReportRepository) -> None:
        self._repository = repository

    def handle(self, command: DeleteReportCommand) -> Result[None]:
        self._repository.remove(command.user_id, command.report_id)
        return Result.success(None)


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
    ) -> None:
        self._work_logs = work_logs
        self._quick_logs = quick_logs
        self._calendar_events = calendar_events
        self._templates = templates

    def handle(self, command: GenerateReportCommand) -> Result[GeneratedReport]:
        try:
            period = validate_report_period(
                command.report_type,
                command.period_start,
                command.period_end,
            )
            standard_hours = max(float(command.standard_work_hours), 0.0)
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))

        work_logs = tuple(
            work_log
            for work_log in self._work_logs.list_all(command.user_id)
            if period.start <= work_log.day <= period.end
        )
        quick_logs = self._quick_logs.list_for_range(
            command.user_id,
            period.start,
            period.end,
        )
        events = self._calendar_events.list_for_range(
            command.user_id,
            period.start,
            period.end,
        )
        template = self._templates.get_template(
            command.language,
            period.report_type,
            user_id=command.user_id,
        )
        if not template.ok or not template.value:
            content = _fallback_report(period.report_type, period.start, period.end)
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
        "task_list": _work_log_lines(work_logs, standard_hours),
        "calendar_events": _event_lines(events),
        "quick_logs": _quick_log_lines(quick_logs),
        "total_hours": f"{total:.1f}",
        "overtime_hours": f"{overtime:.1f}",
        "issues": "- ",
        "next_plan": "- ",
    }


def _work_log_lines(work_logs: tuple[WorkLog, ...], standard_hours: float) -> str:
    if not work_logs:
        return "- No notes recorded for this period."
    lines: list[str] = []
    for work_log in sorted(work_logs, key=lambda item: item.day):
        if work_log.is_leave:
            suffix = f" [{work_log.work_type.value}]"
            note = f" - {work_log.note}" if work_log.note else ""
            lines.append(f"- {work_log.day.isoformat()}{suffix}{note}")
            continue
        hours = work_log.worked_hours()
        overtime = max(hours - standard_hours, 0.0)
        parts = [f"- {work_log.day.isoformat()}: {hours:.1f}h"]
        if overtime > 0:
            parts.append(f"OT+{overtime:.1f}h")
        if work_log.is_overnight:
            parts.append("Night")
        if work_log.note:
            parts.append(work_log.note)
        lines.append("  ".join(parts))
    return "\n".join(lines)


def _quick_log_lines(quick_logs: tuple[QuickLog, ...]) -> str:
    if not quick_logs:
        return "- "
    lines: list[str] = []
    for quick_log in sorted(quick_logs, key=lambda item: (item.day, item.start_time, item.id or 0)):
        time_text = _time_range(quick_log.start_time, quick_log.end_time)
        prefix = f"{quick_log.day.isoformat()} {time_text}".strip()
        lines.append(f"- {prefix}: {quick_log.description}")
    return "\n".join(lines)


def _event_lines(events: tuple[CalendarEvent, ...]) -> str:
    if not events:
        return "- "
    lines: list[str] = []
    for event in sorted(events, key=lambda item: (item.day, item.start_time or "", item.summary)):
        time_text = "All day" if event.all_day else _time_range(event.start_time, event.end_time)
        prefix = f"{event.day.isoformat()} {time_text}".strip()
        lines.append(f"- {prefix}: {event.summary}")
    return "\n".join(lines)


def _time_range(start_time: str | None, end_time: str | None) -> str:
    start = str(start_time or "").strip()
    end = str(end_time or "").strip()
    if start and end:
        return f"{start}-{end}"
    return start or end


def _fallback_report(report_type: str, start: date, end: date) -> str:
    if report_type == "daily":
        title = "Daily Work Report"
    elif report_type == "weekly":
        title = "Weekly Work Report"
    else:
        title = "Monthly Work Report"
    return f"# {title}  {start.isoformat()} - {end.isoformat()}\n\n- "
