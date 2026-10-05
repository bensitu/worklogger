"""CSV import adapter for work logs."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
import io

from worklogger.app.use_cases.data_portability import (
    WorkLogCsvParseResult,
    WorkLogCsvRowDraft,
    WorkLogCsvRowError,
)
from worklogger.domain.shared.errors import InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import get_language


class WorkLogCsvImporter:
    def __init__(self, *, max_bytes: int = 10 * 1024 * 1024, max_rows: int = 50_000, encoding: str | None = None) -> None:
        self._max_bytes = max_bytes
        self._max_rows = max_rows
        self._encoding = encoding

    def parse(self, source: Path, user_id: int) -> Result[WorkLogCsvParseResult]:
        del user_id
        path = Path(source)
        rows: list[WorkLogCsvRowDraft] = []
        errors: list[WorkLogCsvRowError] = []
        try:
            with path.open("rb") as source_file:
                data = source_file.read(self._max_bytes + 1)
            if len(data) > self._max_bytes:
                return Result.failure(ValidationError("csv_file_too_large", "csv_file_too_large"))
            try:
                text = data.decode(self._encoding or "utf-8-sig")
            except UnicodeDecodeError:
                if self._encoding:
                    raise
                encoding = {"ja_JP": "cp932", "ko_KR": "cp949", "zh_CN": "gb18030", "zh_TW": "big5"}.get(get_language(), "utf-8-sig")
                text = data.decode(encoding)
            with io.StringIO(text, newline="") as handle:
                reader = csv.DictReader(handle, strict=True)
                headers = reader.fieldnames or []
                if not ({"date", "d"} & set(headers)):
                    return Result.failure(ValidationError("csv_import_failed", "csv_import_failed"))
                for row_number, row in enumerate(reader, start=2):
                    if row_number > self._max_rows + 1:
                        return Result.failure(ValidationError("csv_file_too_large", "csv_file_too_large"))
                    parsed = _parse_row(row_number, row)
                    if isinstance(parsed, WorkLogCsvRowError):
                        errors.append(parsed)
                    else:
                        rows.append(parsed)
        except (OSError, UnicodeError, csv.Error, LookupError) as exc:
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
            day=_parse_date(day_text),
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


def _parse_date(text: str) -> date:
    parts = text.replace("/", "-").split("-")
    if len(parts) != 3 or len(parts[0]) != 4:
        raise ValueError("date_invalid")
    return date(*(int(part) for part in parts))

