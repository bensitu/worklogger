"""Reports presentation ViewModel."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from calendar import monthrange
from worklogger.infrastructure.i18n import _
from worklogger.domain.reporting.export_selection import latest_daily_reports
from pathlib import Path
from typing import Protocol

from worklogger.app.commands.ai_commands import RewriteTextCommand
from worklogger.app.commands.report_commands import (
    GenerateReportCommand,
    DeleteReportCommand,
    ResetReportTemplateCommand,
    SaveReportCommand,
    SaveReportTemplateCommand,
)
from worklogger.app.queries.report_queries import GetReportForPeriodQuery, ListReportsQuery
from worklogger.app.ports import (
    MarkdownExporter,
    ResetTemplateHandlerProtocol,
    RewriteTextHandlerProtocol,
    SaveTemplateHandlerProtocol,
)
from worklogger.app.use_cases.reports import GeneratedReport, TemplateProvider
from worklogger.domain.reporting.models import Report, ReportProvenance
from worklogger.domain.reporting.periods import (
    daily_period,
    monthly_period,
    normalize_report_type,
    weekly_period,
)
from worklogger.domain.reporting.templates import ReportTemplate
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result


class GenerateReportHandlerProtocol(Protocol):
    def handle(self, command: GenerateReportCommand) -> Result[GeneratedReport]:
        ...


class GetReportForPeriodHandlerProtocol(Protocol):
    def handle(self, query: GetReportForPeriodQuery) -> Result[Report | None]:
        ...


class ListReportsHandlerProtocol(Protocol):
    def handle(self, query: ListReportsQuery) -> Result[tuple[Report, ...]]:
        ...


class SaveReportHandlerProtocol(Protocol):
    def handle(self, command: SaveReportCommand) -> Result[Report]:
        ...


class DeleteReportHandlerProtocol(Protocol):
    def handle(self, command: DeleteReportCommand) -> Result[None]:
        ...


@dataclass(frozen=True)
class ReportEditorState:
    user_id: int
    report_type: str
    period_start: date
    period_end: date
    content: str
    saved: bool = False
    report_id: int | None = None
    created_at: datetime | None = None
    revision: int = 0
    updated_at: datetime | None = None
    provenance: ReportProvenance = ReportProvenance()


@dataclass(frozen=True)
class ReportHistoryItem:
    report_id: int | None
    user_id: int
    report_type: str
    period_start: date
    period_end: date
    content: str
    saved: bool = True
    created_at: datetime | None = None
    revision: int = 0
    updated_at: datetime | None = None
    provenance: ReportProvenance = ReportProvenance()


class ReportEditorViewModel:
    def __init__(
        self,
        *,
        user_id: int,
        generate_handler: GenerateReportHandlerProtocol,
        get_report_handler: GetReportForPeriodHandlerProtocol,
        save_report_handler: SaveReportHandlerProtocol,
        save_template_handler: SaveTemplateHandlerProtocol,
        reset_template_handler: ResetTemplateHandlerProtocol,
        markdown_exporter: MarkdownExporter,
        rewrite_handler: RewriteTextHandlerProtocol,
        list_reports_handler: ListReportsHandlerProtocol | None = None,
        language: str = "en_US",
        standard_work_hours: float = 8.0,
        templates: TemplateProvider | None = None,
        week_start_monday: bool = False,
        delete_report_handler: DeleteReportHandlerProtocol | None = None,
        timesheet_export_handler=None,
        revision_service=None,
    ) -> None:
        self._user_id = user_id
        self._generate_handler = generate_handler
        self._get_report_handler = get_report_handler
        self._save_report_handler = save_report_handler
        self._save_template_handler = save_template_handler
        self._reset_template_handler = reset_template_handler
        self._markdown_exporter = markdown_exporter
        self._rewrite_handler = rewrite_handler
        self._list_reports_handler = list_reports_handler
        self._language = language
        self._standard_work_hours = standard_work_hours
        self._templates = templates
        self._week_start_monday = week_start_monday
        self._delete_report_handler = delete_report_handler
        self._timesheet_export_handler = timesheet_export_handler
        self._revision_service = revision_service

    @property
    def revisions_available(self):
        return self._revision_service is not None

    def list_revisions(self, state):
        if not self.revisions_available or state.user_id != self._user_id or state.report_id is None:
            return Result.failure(_validation("report_not_found"))
        return self._revision_service.list(self._user_id, state.report_id)

    def restore_revision(self, state, revision):
        if not self.revisions_available or state.user_id != self._user_id or state.report_id is None:
            return Result.failure(_validation("report_not_found"))
        result = self._revision_service.restore(self._user_id, state.report_id, revision, state.revision)
        if not result.ok:
            return result
        row = result.value
        return Result.success(ReportEditorState(row.user_id, row.report_type, row.period_start, row.period_end,
            row.content, True, row.id, row.created_at, row.revision, row.updated_at, row.provenance))

    def generate_with_sources(self, state):
        return self._generate_handler.handle(GenerateReportCommand(self._user_id, state.report_type,
            state.period_start, state.period_end, self._language, self._standard_work_hours))

    @property
    def timesheet_available(self):
        return self._timesheet_export_handler is not None

    def export_timesheet(self, destination, selected_day, *, whole_month=False, format="xlsx"):
        if not self.timesheet_available:
            return Result.failure(_validation("timesheet_format_invalid"))
        period = monthly_period(selected_day.year, selected_day.month) if whole_month else daily_period(selected_day)
        return self._timesheet_export_handler.handle(self._user_id, period.start, period.end, destination,
                                                     format=format, standard_hours=self._standard_work_hours)

    @property
    def delete_available(self) -> bool:
        return self._delete_report_handler is not None

    @property
    def saved_export_available(self) -> bool:
        return self._list_reports_handler is not None

    def delete(self, item: ReportHistoryItem) -> Result[None]:
        if item.user_id != self._user_id or item.report_id is None:
            return Result.failure(_validation("report_not_found"))
        if self._delete_report_handler is None:
            return Result.failure(_validation("report_delete_failed"))
        return self._delete_report_handler.handle(DeleteReportCommand(self._user_id, item.report_id, item.content))

    def set_week_start_monday(self, enabled: bool) -> None:
        self._week_start_monday = bool(enabled)

    @property
    def rewrite_available(self) -> bool:
        return bool(getattr(self._rewrite_handler, "available", True))

    def set_standard_work_hours(self, hours: float) -> None:
        self._standard_work_hours = max(1.0, min(float(hours), 24.0))

    def load_template(self, report_type: str) -> Result[str]:
        if self._templates is None:
            return Result.failure(_validation("template_not_configured"))
        return self._templates.get_template(self._language, report_type, self._user_id)

    def generate_draft(self, state: ReportEditorState) -> Result[str]:
        result = self._generate_handler.handle(GenerateReportCommand(
            self._user_id, state.report_type, state.period_start, state.period_end,
            self._language, self._standard_work_hours,
        ))
        if not result.ok or result.value is None:
            return Result.failure(result.error or _validation("report_generate_failed"))
        return Result.success(result.value.content)

    def load(self, report_type: str, selected_day: date) -> Result[ReportEditorState]:
        try:
            period = _period_for(report_type, selected_day, self._week_start_monday)
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        saved = self._get_report_handler.handle(
            GetReportForPeriodQuery(
                user_id=self._user_id,
                report_type=period.report_type,
                period_start=period.start,
                period_end=period.end,
            )
        )
        if not saved.ok:
            return Result.failure(saved.error or _validation("report_load_failed"))
        if saved.value is not None:
            return Result.success(
                ReportEditorState(
                    user_id=self._user_id,
                    report_type=period.report_type,
                    period_start=period.start,
                    period_end=period.end,
                    content=saved.value.content,
                    saved=True,
                    report_id=saved.value.id,
                    created_at=saved.value.created_at,
                    revision=saved.value.revision,
                    updated_at=saved.value.updated_at,
                    provenance=saved.value.provenance,
                )
            )
        generated = self._generate_handler.handle(
            GenerateReportCommand(
                user_id=self._user_id,
                report_type=period.report_type,
                period_start=period.start,
                period_end=period.end,
                language=self._language,
                standard_work_hours=self._standard_work_hours,
            )
        )
        if not generated.ok or generated.value is None:
            return Result.failure(generated.error or _validation("report_generate_failed"))
        return Result.success(
            ReportEditorState(
                user_id=self._user_id,
                report_type=generated.value.report_type,
                period_start=generated.value.period_start,
                period_end=generated.value.period_end,
                content=generated.value.content,
                saved=False,
                provenance=generated.value.provenance,
            )
        )

    def save(self, state: ReportEditorState, content: str) -> Result[ReportEditorState]:
        saved = self._save_report_handler.handle(
            SaveReportCommand(
                user_id=self._user_id,
                report_type=state.report_type,
                period_start=state.period_start,
                period_end=state.period_end,
                content=content,
                report_id=state.report_id,
                revision=state.revision,
                provenance=state.provenance,
            )
        )
        if not saved.ok or saved.value is None:
            return Result.failure(saved.error or _validation("report_save_failed"))
        return Result.success(
            ReportEditorState(
                user_id=self._user_id,
                report_type=state.report_type,
                period_start=state.period_start,
                period_end=state.period_end,
                content=saved.value.content,
                saved=True,
                report_id=saved.value.id,
                created_at=saved.value.created_at,
                revision=saved.value.revision,
                updated_at=saved.value.updated_at,
                provenance=saved.value.provenance,
            )
        )

    def save_template(self, report_type: str, content: str) -> Result[ReportTemplate]:
        return self._save_template_handler.handle(
            SaveReportTemplateCommand(
                user_id=self._user_id,
                language=self._language,
                template_type=report_type,
                content=content,
            )
        )

    def reset_template(self, report_type: str) -> Result[None]:
        return self._reset_template_handler.handle(
            ResetReportTemplateCommand(
                user_id=self._user_id,
                language=self._language,
                template_type=report_type,
            )
        )

    def export_markdown(self, destination: Path, content: str) -> Result[Path]:
        return self._markdown_exporter.export_markdown(destination, content)

    def export_with_sources(self, destination, state, content):
        return self._markdown_exporter.export_markdown(destination, self._annotated_content(state, content))

    @staticmethod
    def _annotated_content(state, content):
        labels = {"daily": _("Daily Report"), "weekly": _("Weekly Report"), "monthly": _("Monthly Report")}
        identity = _("Report #{report_id}").format(report_id=getattr(state, "report_id", getattr(state, "id", None)))
        if getattr(state, "report_id", getattr(state, "id", None)) is None:
            identity = _("Draft")
        lines = [labels[state.report_type] + " | " + identity,
                 state.period_start.isoformat() + " - " + state.period_end.isoformat(),
                 _("Version {number}").format(number=state.revision + 1)]
        if state.updated_at:
            lines.append(_("Last saved: {time}").format(time=state.updated_at.isoformat()))
        from worklogger.presentation.report_source_labels import provenance_text
        lines.extend(["", content, "", "---", "", _("Sources"), provenance_text(state.provenance)])
        return "\n".join(lines)

    @property
    def language(self):
        return self._language

    def export_saved_daily(self, destination: Path, selected_day: date, *, whole_month=False):
        if self._list_reports_handler is None:
            return Result.failure(_validation("report_history_failed"))
        start = selected_day.replace(day=1) if whole_month else selected_day
        end = selected_day.replace(day=monthrange(selected_day.year, selected_day.month)[1]) if whole_month else selected_day
        result = self._list_reports_handler.handle(ListReportsQuery(self._user_id, "daily", start, end))
        if not result.ok:
            return Result.failure(result.error)
        reports = latest_daily_reports(result.value or (), self._user_id, start, end)
        if not reports:
            return Result.failure(_validation("report_export_empty"))
        content = "\n\n".join(self._annotated_content(row, row.content) for row in reports)
        return self._markdown_exporter.export_markdown(destination, content)

    def list_history(self, report_type: str) -> Result[tuple[ReportHistoryItem, ...]]:
        if self._list_reports_handler is None:
            return Result.success(())
        try:
            normalized = normalize_report_type(report_type)
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        result = self._list_reports_handler.handle(
            ListReportsQuery(self._user_id, normalized)
        )
        if not result.ok or result.value is None:
            return Result.failure(result.error or _validation("report_history_failed"))
        return Result.success(
            tuple(
                ReportHistoryItem(
                    report_id=report.id,
                    user_id=report.user_id,
                    report_type=report.report_type,
                    period_start=report.period_start,
                    period_end=report.period_end,
                    content=report.content,
                    saved=True,
                    created_at=report.created_at,
                    revision=report.revision,
                    updated_at=report.updated_at,
                    provenance=report.provenance,
                )
                for report in result.value
            )
        )

    def rewrite(self, state: ReportEditorState, content: str, instructions: str = "") -> Result[str]:
        result = self._rewrite_handler.handle(
            RewriteTextCommand(
                user_id=self._user_id,
                content=content,
                context=f"{state.report_type}_report",
                language=self._language,
                instructions=instructions,
            )
        )
        if not result.ok or result.value is None:
            return Result.failure(result.error or _validation("rewrite_failed"))
        return Result.success(result.value.content)


def _period_for(report_type: str, selected_day: date, week_start_monday: bool = False):
    normalized = str(report_type or "").strip().lower()
    if normalized == "daily":
        return daily_period(selected_day)
    if normalized == "weekly":
        return weekly_period(selected_day, week_start_monday)
    if normalized == "monthly":
        return monthly_period(selected_day.year, selected_day.month)
    raise ValueError("invalid_report_type")


def _validation(code: str) -> ValidationError:
    return ValidationError(code, code)
