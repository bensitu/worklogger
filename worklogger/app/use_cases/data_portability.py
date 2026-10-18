"""Data-portability use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

from worklogger.app.commands.data_portability_commands import ImportWorkLogsCsvCommand
from worklogger.app.use_cases._errors import infrastructure_failure
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkLog, WorkModeValue
from worklogger.domain.projects.models import WorkContext
from worklogger.domain.worklog.repositories import WorkLogRepository
from worklogger.domain.worklog.rules import decode_entry_type, normalize_work_log
from worklogger.domain.worklog.intervals import EntryIntervalIndex


@dataclass(frozen=True)
class WorkLogCsvRowDraft:
    row_number: int
    day: date
    start_time: str | None
    end_time: str | None
    break_hours: float
    note: str
    entry_type: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    entry_type_label: str = ""
    entry_type_category: str = ""
    project_label: str = ""
    work_item_label: str = ""
    work_mode: WorkModeValue | None = None


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
    existing_date_count: int = 0


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
            return Result.failure(preview.error or ValidationError("csv_import_failed", "csv_import_failed"))
        return self.apply(preview.value, overwrite=command.overwrite_existing, replace_dates=command.replace_dates)

    def preview(self, command: ImportWorkLogsCsvCommand) -> Result[WorkLogCsvImportPreview]:
        parsed = self._importer.parse(Path(command.source_path), command.user_id)
        if not parsed.ok or parsed.value is None:
            return Result.failure(parsed.error or ValidationError("csv_import_failed", "csv_import_failed"))
        rows = []
        dates = set()
        candidates = []
        timed_dates, untimed_dates, note_dates = set(), set(), set()
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
                        entry_type=decode_entry_type(row.entry_type, label=row.entry_type_label, category=row.entry_type_category, strict=True),
                        started_at=row.started_at,
                        ended_at=row.ended_at,
                        context=WorkContext(project_label=row.project_label, work_item_label=row.work_item_label),
                        work_mode=row.work_mode,
                    )
                )
                candidates.append((row, work_log))
            except (TypeError, ValueError) as exc:
                errors.append(WorkLogCsvRowError(row.row_number, str(exc)))
        intervals = EntryIntervalIndex(record for _row, record in candidates)
        for row, work_log in candidates:
            try:
                if work_log.is_note_only:
                    if row.day in note_dates:
                        raise ValueError("duplicate_date")
                    note_dates.add(row.day)
                elif not work_log.has_times:
                    if row.day in untimed_dates or row.day in timed_dates:
                        raise ValueError("duplicate_date")
                    untimed_dates.add(row.day)
                else:
                    if row.day in untimed_dates:
                        raise ValueError("duplicate_date")
                    if not intervals.add(work_log):
                        raise ValueError("worklog_entry_overlap")
                    timed_dates.add(row.day)
                dates.add(row.day)
            except (TypeError, ValueError) as exc:
                errors.append(WorkLogCsvRowError(row.row_number, str(exc)))
                continue
            rows.append(work_log)
        try:
            targeted = getattr(self._repository, "existing_dates", None)
            if targeted is not None:
                existing = targeted(command.user_id, dates)
            else:
                reader = getattr(self._repository, "list_export_rows", self._repository.list_all)
                existing = {row.day for row in reader(command.user_id)}
        except Exception as error:
            return Result.failure(infrastructure_failure("csv_import_failed", error, logger_name=__name__))
        return Result.success(WorkLogCsvImportPreview(tuple(rows), tuple(errors), len(existing & dates)))

    def apply(self, preview: WorkLogCsvImportPreview, *, overwrite: bool = False,
              replace_dates: bool = False) -> Result[WorkLogCsvImportResult]:
        try:
            self._repository.import_many(preview.rows, overwrite=overwrite, replace_dates=replace_dates)
        except ValueError as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        except Exception as error:
            return Result.failure(infrastructure_failure("csv_import_failed", error, logger_name=__name__))
        return Result.success(
            WorkLogCsvImportResult(
                imported_count=len(preview.rows),
                errors=preview.errors,
            )
        )

