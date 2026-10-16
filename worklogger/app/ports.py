"""Application-layer Protocols for optional infrastructure adapters."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TYPE_CHECKING

from worklogger.app.commands.ai_commands import RewriteTextCommand
from worklogger.app.job_runner import CancellationToken
from worklogger.app.commands.report_commands import ResetReportTemplateCommand, SaveReportTemplateCommand
from worklogger.domain.reporting.templates import ReportTemplate
from worklogger.domain.worklog.models import CustomWorkType, WorkLog, WorkType
from worklogger.domain.projects.models import WorkContext, Project, WorkItem
from worklogger.domain.reporting.timesheets import Timesheet
from worklogger.domain.shared.result import Result

if TYPE_CHECKING:
    from worklogger.app.use_cases.ai import RewriteTextResult


@dataclass(frozen=True)
class AIRequest:
    messages: tuple[Mapping[str, str], ...]
    model: str
    timeout_seconds: float
    cancellation_token: CancellationToken | None = None
    local_messages: tuple[Mapping[str, str], ...] | None = None


@dataclass(frozen=True)
class AIResponse:
    text: str
    provider: str


class AIGateway(Protocol):
    def generate(self, request: AIRequest) -> Result[AIResponse]:
        ...


class KeyStore(Protocol):
    def get_secret(self, name: str) -> Result[str | None]:
        ...

    def set_secret(self, name: str, value: str) -> Result[None]:
        ...


class BackupService(Protocol):
    def backup_database(self, destination: Path) -> Result[Path]:
        ...

    def restore_database(self, source: Path) -> Result[None]:
        ...

    def validate_restore_database(self, source: Path) -> Result[None]:
        ...


class UpdateChecker(Protocol):
    def check_latest_version(self, current_version: str) -> Result[str | None]:
        ...


class MarkdownExporter(Protocol):
    def export_markdown(self, destination: Path, content: str) -> Result[Path]:
        ...


class TemplateProvider(Protocol):
    def get_template(self, language: str, template_type: str,
                     user_id: int | None = None) -> Result[str]: ...


class TimesheetExporter(Protocol):
    def export_timesheet(self, destination: Path, snapshot: Timesheet) -> Result[Path]: ...


class SaveTemplateHandlerProtocol(Protocol):
    def handle(self, command: SaveReportTemplateCommand) -> Result[ReportTemplate]:
        ...


class ResetTemplateHandlerProtocol(Protocol):
    def handle(self, command: ResetReportTemplateCommand) -> Result[None]:
        ...


class RewriteTextHandlerProtocol(Protocol):
    def handle(self, command: RewriteTextCommand, cancellation_token: CancellationToken | None = None) -> Result[RewriteTextResult]:
        ...


class WorkLogCsvExporter(Protocol):
    def export_work_logs(
        self,
        destination: Path,
        rows: Iterable[WorkLog],
    ) -> Result[Path]:
        ...


class WorkLogIcsExporter(Protocol):
    def write_work_logs(
        self,
        destination: Path,
        rows: Iterable[WorkLog],
    ) -> Result[Path]:
        ...


class WorkTypeOperations(Protocol):
    def list_types(self) -> Result[tuple[CustomWorkType, ...]]: ...
    def save(self, label: str, category: str, previous: CustomWorkType | None = None) -> Result[CustomWorkType]: ...
    def archive(self, definition: CustomWorkType) -> Result[None]: ...
    def resolve(self, value: str, original: WorkType | CustomWorkType | None = None) -> WorkType | CustomWorkType: ...


class ProjectOperations(Protocol):
    def recent_contexts(self) -> Result[tuple[WorkContext, ...]]: ...
    def catalog(self) -> Result[tuple[tuple[Project, ...], dict[str, tuple[WorkItem, ...]]]]: ...
    def list_projects(self) -> Result[tuple[Project, ...]]: ...
    def list_work_items(self, project_id: str) -> Result[tuple[WorkItem, ...]]: ...
    def save_project(self, name: str, code: str = "", previous: Project | None = None) -> Result[Project]: ...
    def save_work_item(self, project_id: str, title: str, source_url: str = "", completed: bool = False, previous: WorkItem | None = None) -> Result[WorkItem]: ...
    def archive_project(self, project: Project) -> Result[Project]: ...
    def archive_work_item(self, item: WorkItem) -> Result[WorkItem]: ...
    def resolve(self, context: WorkContext, original: WorkContext | None = None) -> WorkContext: ...
