"""Data-portability use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from worklogger.app.commands.data_portability_commands import ImportWorkLogsCsvCommand
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkLog
from worklogger.domain.worklog.repositories import WorkLogRepository
from worklogger.domain.worklog.rules import normalize_work_log, normalize_work_type


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
        parsed = self._importer.parse(Path(command.source_path), command.user_id)
        if not parsed.ok or parsed.value is None:
            return Result.failure(parsed.error or ValidationError("csv_import_failed", "csv_import_failed"))
        imported = 0
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
                        work_type=normalize_work_type(row.work_type),
                    )
                )
            except (TypeError, ValueError) as exc:
                errors.append(WorkLogCsvRowError(row.row_number, str(exc)))
                continue
            self._repository.save(work_log)
            imported += 1
        return Result.success(
            WorkLogCsvImportResult(
                imported_count=imported,
                errors=tuple(errors),
            )
        )

