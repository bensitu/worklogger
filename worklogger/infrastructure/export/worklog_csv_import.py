"""CSV import adapter for work logs."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from worklogger.app.use_cases.data_portability import (
    WorkLogCsvParseResult,
    WorkLogCsvRowDraft,
    WorkLogCsvRowError,
)
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result


class WorkLogCsvImporter:
    def parse(self, source: Path, user_id: int) -> Result[WorkLogCsvParseResult]:
        del user_id
        path = Path(source)
        rows: list[WorkLogCsvRowDraft] = []
        errors: list[WorkLogCsvRowError] = []
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                for row_number, row in enumerate(reader, start=2):
                    parsed = _parse_row(row_number, row)
                    if isinstance(parsed, WorkLogCsvRowError):
                        errors.append(parsed)
                    else:
                        rows.append(parsed)
        except OSError as exc:
            return Result.failure(
                InfrastructureError(
                    "csv_import_failed",
                    "csv_import_failed",
                    {"reason": str(exc)},
                )
            )
        return Result.success(
            WorkLogCsvParseResult(
                rows=tuple(rows),
                errors=tuple(errors),
            )
        )


def _parse_row(
    row_number: int,
    row: dict[str, str | None],
) -> WorkLogCsvRowDraft | WorkLogCsvRowError:
    try:
        day_text = _field(row, "date") or _field(row, "d")
        if not day_text:
            raise ValueError("date_required")
        break_text = _field(row, "break") or _field(row, "lunch") or "0"
        return WorkLogCsvRowDraft(
            row_number=row_number,
            day=date.fromisoformat(day_text),
            start_time=_optional(_field(row, "start")),
            end_time=_optional(_field(row, "end")),
            break_hours=float(break_text),
            note=_field(row, "note"),
            work_type=_field(row, "work_type") or "normal",
        )
    except Exception as exc:
        return WorkLogCsvRowError(row_number, str(exc))


def _field(row: dict[str, str | None], key: str) -> str:
    return str(row.get(key) or "").strip()


def _optional(value: str) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None

