"""Data-portability use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from worklogger.app.commands.data_portability_commands import ImportWorkLogsCsvCommand
from worklogger.domain.shared.errors import InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkLog
from worklogger.domain.worklog.repositories import WorkLogRepository
from worklogger.domain.worklog.rules import normalize_work_log
from worklogger.domain.worklog.models import WorkType


@dataclass(frozen=True)
class WorkLogCsvRowDraft:
    row_number: int
    day: date
    start_time: str | None
    end_time: str | None
    break_hours: float
    note: str
    work_type: str


@dataclass(frozen=True)
class WorkLogCsvRowError:
    row_number: int
    message: str


@dataclass(frozen=True)
class WorkLogCsvParseResult:
    rows: tuple[WorkLogCsvRowDraft, ...]
    errors: tuple[WorkLogCsvRowError, ...] = ()


@dataclass(frozen=True)
class WorkLogCsvImportResult:
    imported_count: int
    errors: tuple[WorkLogCsvRowError, ...] = ()


@dataclass(frozen=True)
class WorkLogCsvImportPreview:
    rows: tuple[WorkLog, ...]
    errors: tuple[WorkLogCsvRowError, ...] = ()
    existing_count: int = 0


class WorkLogCsvImporter(Protocol):
    def parse(self, source: Path, user_id: int) -> Result[WorkLogCsvParseResult]:
        ...


class ImportWorkLogsCsvHandler:
    def __init__(
        self,
        *,
        importer: WorkLogCsvImporter,
        repository: WorkLogRepository,
    ) -> None:
        self._importer = importer
        self._repository = repository

    def handle(self, command: ImportWorkLogsCsvCommand) -> Result[WorkLogCsvImportResult]:
        preview = self.preview(command)
        if not preview.ok or preview.value is None:
            return Result.failure(preview.error)
        return self.apply(preview.value, overwrite=command.overwrite_existing)

    def preview(self, command: ImportWorkLogsCsvCommand) -> Result[WorkLogCsvImportPreview]:
        parsed = self._importer.parse(Path(command.source_path), command.user_id)
        if not parsed.ok or parsed.value is None:
            return Result.failure(parsed.error or ValidationError("csv_import_failed", "csv_import_failed"))
        rows = []
        dates = set()
        errors = list(parsed.value.errors)
        for row in parsed.value.rows:
            try:
                work_log = normalize_work_log(
                    WorkLog(
                        user_id=command.user_id,
                        day=row.day,
                        start_time=row.start_time,
                        end_time=row.end_time,
                        break_hours=row.break_hours,
                        note=row.note,
                        work_type=WorkType(row.work_type),
                    )
                )
                if row.day in dates:
                    raise ValueError("duplicate_date")
                dates.add(row.day)
            except (TypeError, ValueError) as exc:
                errors.append(WorkLogCsvRowError(row.row_number, str(exc)))
                continue
            rows.append(work_log)
        try:
            reader = getattr(self._repository, "list_export_rows", self._repository.list_all)
            existing = {row.day for row in reader(command.user_id)}
        except Exception:
            return Result.failure(InfrastructureError("csv_import_failed", "csv_import_failed"))
        return Result.success(WorkLogCsvImportPreview(tuple(rows), tuple(errors), len(existing & dates)))

    def apply(self, preview: WorkLogCsvImportPreview, *, overwrite: bool = False) -> Result[WorkLogCsvImportResult]:
        try:
            self._repository.import_many(preview.rows, overwrite=overwrite)
        except ValueError as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        except Exception:
            return Result.failure(InfrastructureError("csv_import_failed", "csv_import_failed"))
        return Result.success(
            WorkLogCsvImportResult(
                imported_count=len(preview.rows),
                errors=preview.errors,
            )
        )

