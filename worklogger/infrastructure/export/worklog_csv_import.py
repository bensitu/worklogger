"""CSV import adapter for work logs."""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path
import io
from collections.abc import Callable

from worklogger.app.use_cases.data_portability import (
    WorkLogCsvParseResult,
    WorkLogCsvRowDraft,
    WorkLogCsvRowError,
)
from worklogger.domain.shared.errors import CancellationError, InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import get_language
from worklogger.infrastructure.export.csv_text import decode_text
from worklogger.domain.worklog.models import decode_work_mode


class WorkLogCsvImporter:
    def __init__(self, *, max_bytes: int = 10 * 1024 * 1024, max_rows: int = 50_000, encoding: str | None = None) -> None:
        self._max_bytes = max_bytes
        self._max_rows = max_rows
        self._encoding = encoding

    def parse(self, source: Path, user_id: int, *, is_cancelled: Callable[[], bool] | None = None) -> Result[WorkLogCsvParseResult]:
        del user_id
        if is_cancelled is not None and is_cancelled():
            return Result.failure(CancellationError("job_cancelled", "job_cancelled"))
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
                headers = [str(header).strip().casefold() for header in (reader.fieldnames or [])]
                if len(headers) != len(set(headers)):
                    return Result.failure(ValidationError("csv_import_failed", "csv_import_failed"))
                reader.fieldnames = headers
                if not ({"date", "d"} & set(headers)):
                    return Result.failure(ValidationError("csv_import_failed", "csv_import_failed"))
                for row_number, row in enumerate(reader, start=2):
                    if is_cancelled is not None and is_cancelled():
                        return Result.failure(CancellationError("job_cancelled", "job_cancelled"))
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
                    {"reason": type(exc).__name__},
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
            note=_text_field(row, "note"),
            entry_type=_text_field(row, "entry_type") or _text_field(row, "work_type") or "normal",
            started_at=datetime.fromisoformat(_field(row, "started_at")) if _field(row, "started_at") else None,
            ended_at=datetime.fromisoformat(_field(row, "ended_at")) if _field(row, "ended_at") else None,
            entry_type_label=_text_field(row, "entry_type_label"),
            entry_type_category=_field(row, "entry_type_category"),
            project_label=_text_field(row, "project_label"),
            work_item_label=_text_field(row, "work_item_label"),
            work_mode=decode_work_mode(_field(row, "work_mode") or None, _text_field(row, "work_mode_label")),
        )
    except (TypeError, ValueError, OverflowError):
        return WorkLogCsvRowError(row_number, "csv_import_failed")


def _text_field(row: dict[str, str | None], key: str) -> str:
    return decode_text(_field(row, key), _field(row, "text_format"))


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

