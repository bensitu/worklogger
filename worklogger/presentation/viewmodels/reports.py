"""Reports presentation ViewModel."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from worklogger.app.commands.ai_commands import RewriteTextCommand
from worklogger.app.commands.report_commands import (
    GenerateReportCommand,
    ResetReportTemplateCommand,
    SaveReportCommand,
    SaveReportTemplateCommand,
)
from worklogger.app.queries.report_queries import GetReportForPeriodQuery, ListReportsQuery
from worklogger.app.use_cases.ai import RewriteTextResult
from worklogger.app.use_cases.reports import GeneratedReport
from worklogger.domain.reporting.models import Report
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
class ReportEditorState:
    user_id: int
    report_type: str
    period_start: date
    period_end: date
    content: str
    saved: bool = False


@dataclass(frozen=True)
class ReportHistoryItem:
    report_id: int | None
    user_id: int
    report_type: str
    period_start: date
    period_end: date
    content: str
    saved: bool = True


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
        markdown_exporter: MarkdownExportServiceProtocol,
        rewrite_handler: RewriteTextHandlerProtocol,
        list_reports_handler: ListReportsHandlerProtocol | None = None,
        language: str = "en_US",
        standard_work_hours: float = 8.0,
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

    def load(self, report_type: str, selected_day: date) -> Result[ReportEditorState]:
        try:
            period = _period_for(report_type, selected_day)
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
            )
        )

    def save(self, state: ReportEditorState, content: str) -> Result[ReportEditorState]:
        saved = self._save_report_handler.handle(
            SaveReportCommand(
                user_id=state.user_id,
                report_type=state.report_type,
                period_start=state.period_start,
                period_end=state.period_end,
                content=content,
            )
        )
        if not saved.ok or saved.value is None:
            return Result.failure(saved.error or _validation("report_save_failed"))
        return Result.success(
            ReportEditorState(
                user_id=state.user_id,
                report_type=state.report_type,
                period_start=state.period_start,
                period_end=state.period_end,
                content=saved.value.content,
                saved=True,
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
                )
                for report in result.value
            )
        )

    def rewrite(self, state: ReportEditorState, content: str) -> Result[str]:
        result = self._rewrite_handler.handle(
            RewriteTextCommand(
                user_id=self._user_id,
                content=content,
                context=f"{state.report_type}_report",
                language=self._language,
            )
        )
        if not result.ok or result.value is None:
            return Result.failure(result.error or _validation("rewrite_failed"))
        return Result.success(result.value.content)


def _period_for(report_type: str, selected_day: date):
    normalized = str(report_type or "").strip().lower()
    if normalized == "daily":
        return daily_period(selected_day)
    if normalized == "weekly":
        return weekly_period(selected_day)
    if normalized == "monthly":
        return monthly_period(selected_day.year, selected_day.month)
    raise ValueError("invalid_report_type")


def _validation(code: str) -> ValidationError:
    return ValidationError(code, code)
