"""Data-management presentation ViewModel."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from worklogger.app.commands.calendar_commands import ImportCalendarEventsCommand
from worklogger.app.commands.data_portability_commands import ImportWorkLogsCsvCommand
from worklogger.app.queries.calendar_queries import GetCalendarEventsForRangeQuery
from worklogger.app.queries.work_log_queries import GetAllWorkLogsQuery
from worklogger.app.use_cases.data_portability import WorkLogCsvImportResult
from worklogger.domain.calendar.models import CalendarEvent
from worklogger.domain.shared.errors import InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkLog


class WorkLogListHandler(Protocol):
    def handle(self, query: GetAllWorkLogsQuery) -> Result[tuple[WorkLog, ...]]:
        ...


class CalendarEventsForRangeHandler(Protocol):
    def handle(
        self,
        query: GetCalendarEventsForRangeQuery,
    ) -> Result[tuple[CalendarEvent, ...]]:
        ...


class IcsImportHandler(Protocol):
    def handle(self, command: ImportCalendarEventsCommand) -> Result[int]:
        ...


class WorkLogCsvImportHandler(Protocol):
    def handle(self, command: ImportWorkLogsCsvCommand) -> Result[WorkLogCsvImportResult]:
        ...


class BackupService(Protocol):
    def backup_database(self, destination: Path) -> Result[Path]:
        ...

    def validate_restore_database(self, source: Path) -> Result[None]:
        ...

    def restore_database(self, source: Path) -> Result[None]:
        ...


class CsvExportService(Protocol):
    def export_work_logs(self, destination: Path, rows: Iterable[WorkLog]) -> Result[Path]:
        ...


class IcsExportService(Protocol):
    def write_work_logs(self, destination: Path, rows: Iterable[WorkLog]) -> Result[Path]:
        ...


@dataclass(frozen=True)
class DataManagementActionState:
    action: str
    path: Path | None = None
    record_count: int = 0
    message: str = ""


class DataManagementViewModel:
    def __init__(
        self,
        *,
        user_id: int,
        work_logs_handler: WorkLogListHandler,
        backup_service: BackupService,
        csv_exporter: CsvExportService,
        ics_exporter: IcsExportService,
        calendar_events_handler: CalendarEventsForRangeHandler | None = None,
        ics_import_handler: IcsImportHandler | None = None,
        csv_import_handler: WorkLogCsvImportHandler | None = None,
    ) -> None:
        self._user_id = user_id
        self._work_logs_handler = work_logs_handler
        self._backup_service = backup_service
        self._csv_exporter = csv_exporter
        self._ics_exporter = ics_exporter
        self._calendar_events_handler = calendar_events_handler
        self._ics_import_handler = ics_import_handler
        self._csv_import_handler = csv_import_handler

    def backup_database(self, destination: Path) -> Result[DataManagementActionState]:
        result = self._backup_service.backup_database(Path(destination))
        if not result.ok or result.value is None:
            return Result.failure(result.error or _error("backup_failed"))
        return Result.success(
            DataManagementActionState(
                action="backup",
                path=result.value,
                message="backup_saved",
            )
        )

    def validate_restore_database(self, source: Path) -> Result[DataManagementActionState]:
        result = self._backup_service.validate_restore_database(Path(source))
        if not result.ok:
            return Result.failure(result.error or _error("restore_validation_failed"))
        return Result.success(
            DataManagementActionState(
                action="restore_validate",
                path=Path(source),
                message="restore_valid",
            )
        )

    def restore_database(self, source: Path) -> Result[DataManagementActionState]:
        result = self._backup_service.restore_database(Path(source))
        if not result.ok:
            return Result.failure(result.error or _error("restore_failed"))
        return Result.success(
            DataManagementActionState(
                action="restore",
                path=Path(source),
                message="restore_complete",
            )
        )

    def export_csv(self, destination: Path) -> Result[DataManagementActionState]:
        rows = self._load_rows()
        if not rows.ok or rows.value is None:
            return Result.failure(rows.error or _error("worklog_export_load_failed"))
        result = self._csv_exporter.export_work_logs(Path(destination), rows.value)
        if not result.ok or result.value is None:
            return Result.failure(result.error or _error("csv_export_failed"))
        return Result.success(
            DataManagementActionState(
                action="export_csv",
                path=result.value,
                record_count=len(rows.value),
                message="csv_exported",
            )
        )

    def export_ics(self, destination: Path) -> Result[DataManagementActionState]:
        rows = self._load_rows()
        if not rows.ok or rows.value is None:
            return Result.failure(rows.error or _error("worklog_export_load_failed"))
        result = self._ics_exporter.write_work_logs(Path(destination), rows.value)
        if not result.ok or result.value is None:
            return Result.failure(result.error or _error("ics_export_failed"))
        return Result.success(
            DataManagementActionState(
                action="export_ics",
                path=result.value,
                record_count=len(rows.value),
                message="ics_exported",
            )
        )

    def import_csv(self, source: Path) -> Result[DataManagementActionState]:
        if self._csv_import_handler is None:
            return Result.failure(
                ValidationError("csv_import_unavailable", "csv_import_unavailable")
            )
        result = self._csv_import_handler.handle(
            ImportWorkLogsCsvCommand(
                user_id=self._user_id,
                source_path=Path(source),
            )
        )
        if not result.ok or result.value is None:
            return Result.failure(result.error or _error("csv_import_failed"))
        message = "csv_imported"
        if result.value.errors:
            message = "csv_imported_with_errors"
        return Result.success(
            DataManagementActionState(
                action="import_csv",
                path=Path(source),
                record_count=result.value.imported_count,
                message=message,
            )
        )

    def calendar_event_count(self) -> Result[int]:
        if self._calendar_events_handler is None:
            return Result.success(0)
        result = self._calendar_events_handler.handle(
            GetCalendarEventsForRangeQuery(
                user_id=self._user_id,
                start_day=date.min,
                end_day=date.max,
            )
        )
        if not result.ok or result.value is None:
            return Result.failure(result.error or _error("calendar_event_count_failed"))
        return Result.success(len(result.value))

    def import_ics(
        self,
        source: Path,
        *,
        replace_existing: bool,
    ) -> Result[DataManagementActionState]:
        if self._ics_import_handler is None:
            return Result.failure(
                ValidationError("ics_import_unavailable", "ics_import_unavailable")
            )
        result = self._ics_import_handler.handle(
            ImportCalendarEventsCommand(
                user_id=self._user_id,
                source_path=Path(source),
                replace_existing=replace_existing,
            )
        )
        if not result.ok or result.value is None:
            return Result.failure(result.error or _error("ics_import_failed"))
        return Result.success(
            DataManagementActionState(
                action="import_ics",
                path=Path(source),
                record_count=result.value,
                message="ics_imported",
            )
        )

    def _load_rows(self) -> Result[tuple[WorkLog, ...]]:
        result = self._work_logs_handler.handle(GetAllWorkLogsQuery(self._user_id))
        if not result.ok or result.value is None:
            return Result.failure(
                result.error
                or ValidationError(
                    "worklog_export_load_failed",
                    "worklog_export_load_failed",
                )
            )
        return Result.success(result.value)


def _error(code: str) -> InfrastructureError:
    return InfrastructureError(code, code)
