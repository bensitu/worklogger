"""CSV export adapter for work logs."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
import csv
from worklogger.infrastructure.files import atomic_destination
from worklogger.infrastructure.export.csv_text import TEXT_FORMAT, encode_text, requires_encoding

from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import CustomEntryType, CustomWorkMode, WorkLog, EntryType


class WorkLogCsvExporter:
    HEADER = ("date", "start", "end", "break", "note", "entry_type")

    def export_work_logs(
        self,
        destination: Path,
        rows: Iterable[WorkLog],
    ) -> Result[Path]:
        destination = Path(destination)
        try:
            records = tuple(entry for row in rows for entry in (row.entries or (row,)))
            timestamps = any(row.started_at is not None or row.ended_at is not None for row in records)
            custom_types = any(isinstance(row.entry_type, CustomEntryType) for row in records)
            work_context = any(row.context.label for row in records)
            work_modes = any(row.work_mode is not None for row in records)
            custom_modes = any(isinstance(row.work_mode, CustomWorkMode) for row in records)
            encoded = any(requires_encoding((row.note, _entry_type_value(row.entry_type),
                row.entry_type.label if isinstance(row.entry_type, CustomEntryType) else "",
                row.context.project_label, row.context.work_item_label,
                row.work_mode.label if isinstance(row.work_mode, CustomWorkMode) else "")) for row in records)
            with atomic_destination(destination) as temporary, temporary.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(self.HEADER + (("started_at", "ended_at") if timestamps else ())
                    + (("entry_type_label", "entry_type_category") if custom_types else ())
                    + (("project_label", "work_item_label") if work_context else ())
                    + (("work_mode",) if work_modes else ())
                    + (("work_mode_label",) if custom_modes else ())
                    + (("text_format",) if encoded else ()))
                for row in records:
                    writer.writerow(
                        [
                            row.day.isoformat(),
                            row.start_time or "",
                            row.end_time or "",
                            row.break_hours,
                            encode_text(row.note),
                            encode_text(_entry_type_value(row.entry_type)),
                        ] + ([row.started_at.isoformat() if row.started_at else "", row.ended_at.isoformat() if row.ended_at else ""] if timestamps else [])
                        + ([encode_text(row.entry_type.label), row.entry_type.category] if isinstance(row.entry_type, CustomEntryType)
                           else ["", ""] if custom_types else [])
                        + ([encode_text(row.context.project_label), encode_text(row.context.work_item_label)] if work_context else [])
                        + ([row.work_mode.value if row.work_mode is not None else ""] if work_modes else [])
                        + ([encode_text(row.work_mode.label) if isinstance(row.work_mode, CustomWorkMode) else ""] if custom_modes else [])
                        + ([TEXT_FORMAT] if encoded else [])
                    )
        except Exception as exc:
            return Result.failure(
                InfrastructureError(
                    "csv_export_failed",
                    "csv_export_failed",
                    {"reason": type(exc).__name__},
                )
            )
        return Result.success(destination)


def _entry_type_value(entry_type: EntryType | CustomEntryType | str) -> str:
    if isinstance(entry_type, (EntryType, CustomEntryType)):
        return entry_type.value
    return str(entry_type or EntryType.NORMAL.value)
