"""CSV export adapter for work logs."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
import csv
from worklogger.infrastructure.files import atomic_destination, spreadsheet_text

from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkLog, WorkType


class WorkLogCsvExporter:
    HEADER = ("date", "start", "end", "break", "note", "work_type")

    def export_work_logs(
        self,
        destination: Path,
        rows: Iterable[WorkLog],
    ) -> Result[Path]:
        destination = Path(destination)
        try:
            with atomic_destination(destination) as temporary, temporary.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(self.HEADER)
                for row in rows:
                    writer.writerow(
                        [
                            row.day.isoformat(),
                            row.start_time or "",
                            row.end_time or "",
                            row.break_hours,
                            spreadsheet_text(row.note),
                            spreadsheet_text(_work_type_value(row.work_type)),
                        ]
                    )
        except Exception as exc:
            return Result.failure(
                InfrastructureError(
                    "csv_export_failed",
                    "csv_export_failed",
                    {"reason": str(exc)},
                )
            )
        return Result.success(destination)


def _work_type_value(work_type: WorkType | str) -> str:
    if isinstance(work_type, WorkType):
        return work_type.value
    return str(work_type or WorkType.NORMAL.value)
