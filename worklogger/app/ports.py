"""Application-layer Protocols for optional infrastructure adapters."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from worklogger.domain.worklog.models import WorkLog
from worklogger.domain.shared.result import Result


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


class ExportService(Protocol):
    def export_rows(self, destination: Path, rows: Iterable[object]) -> Result[Path]:
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
