"""Application-layer Protocols for optional infrastructure adapters."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from datetime import date, datetime
from typing import Protocol, TYPE_CHECKING

from worklogger.app.commands.ai_commands import RewriteTextCommand
from worklogger.app.commands.report_commands import ResetReportTemplateCommand, SaveReportTemplateCommand
from worklogger.domain.reporting.templates import ReportTemplate
from worklogger.domain.worklog.models import CustomWorkType, WorkLog, WorkType
from worklogger.domain.shared.result import Result

if TYPE_CHECKING:
    from worklogger.app.use_cases.ai import RewriteTextResult
    from worklogger.app.use_cases.time_entries import EntryTimer


@dataclass(frozen=True)
class AIRequest:
    messages: tuple[Mapping[str, str], ...]
    model: str
    timeout_seconds: float


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


class UpdateChecker(Protocol):
    def check_latest_version(self, current_version: str) -> Result[str | None]:
        ...


class MarkdownExporter(Protocol):
    def export_markdown(self, destination: Path, content: str) -> Result[Path]:
        ...


class SaveTemplateHandlerProtocol(Protocol):
    def handle(self, command: SaveReportTemplateCommand) -> Result[ReportTemplate]:
        ...


class ResetTemplateHandlerProtocol(Protocol):
    def handle(self, command: ResetReportTemplateCommand) -> Result[None]:
        ...


class RewriteTextHandlerProtocol(Protocol):
    def handle(self, command: RewriteTextCommand) -> Result[RewriteTextResult]:
        ...


class WorkLogCsvExporter(Protocol):
    def export_work_logs(
        self,
        destination: Path,
        rows: Iterable[WorkLog],
    ) -> Result[Path]:
        ...


class WorkLogIcsExporter(Protocol):
    def export_work_logs(
        self,
        rows: Iterable[WorkLog],
    ) -> Result[str]:
        ...


class IdentityProvider(Protocol):
    provider_id: str

    def authenticate(self) -> Result[object]:
        ...


class LocalModelManager(Protocol):
    def refresh_catalog(self) -> Result[tuple[object, ...]]:
        ...

    def import_model(self, source: Path) -> Result[object]:
        ...


class WorkTypeOperations(Protocol):
    def list_types(self) -> Result[tuple[CustomWorkType, ...]]: ...
    def save(self, label: str, category: str, previous: CustomWorkType | None = None) -> Result[CustomWorkType]: ...
    def archive(self, definition: CustomWorkType) -> Result[None]: ...
    def resolve(self, value: str, original: WorkType | CustomWorkType | None = None) -> WorkType | CustomWorkType: ...


class TimeEntryOperations(Protocol):
    user_id: int
    timer: EntryTimer | None
    restore_failed: bool
    events_deletable: bool
    work_types: WorkTypeOperations | None

    def now(self) -> datetime: ...
    def list_for_day(self, day: date) -> Result[tuple[WorkLog, ...]]: ...
    def get_entry(self, entry_id: int) -> Result[WorkLog]: ...
    def save_manual(self, day, start, end, work_type, content, original=None): ...
    def start(self, work_type, content, *, now=None, break_entry=None): ...
    def finish(self, content, *, now=None): ...
    def save_content(self, content, completed=None): ...
    def take_break(self, hours, content, *, now=None): ...
    def resume(self, content, *, at_deadline=False, now=None): ...
    def discard_timer(self) -> Result[None]: ...
    def delete(self, record: WorkLog) -> Result[None]: ...
    def delete_event(self, event) -> Result[None]: ...
