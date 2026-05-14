"""ICS export adapter for work logs."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
import re

from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import TimeRange, WorkLog

_LINE_LIMIT_BYTES = 75


class WorkLogIcsExporter:
    def export_work_logs(self, rows: Iterable[WorkLog]) -> Result[str]:
        try:
            return Result.success(_build_calendar(tuple(rows)))
        except Exception as exc:
            return Result.failure(
                InfrastructureError(
                    "ics_export_failed",
                    "ics_export_failed",
                    {"reason": str(exc)},
                )
            )

    def write_work_logs(self, destination: Path, rows: Iterable[WorkLog]) -> Result[Path]:
        generated = self.export_work_logs(rows)
        if not generated.ok:
            return Result.failure(
                generated.error
                or InfrastructureError("ics_export_failed", "ics_export_failed")
            )
        destination = Path(destination)
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("w", encoding="utf-8", newline="") as handle:
                handle.write(generated.value or "")
        except Exception as exc:
            return Result.failure(
                InfrastructureError(
                    "ics_export_failed",
                    "ics_export_failed",
                    {"reason": str(exc)},
                )
            )
        return Result.success(destination)


def _build_calendar(rows: tuple[WorkLog, ...]) -> str:
    dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//WorkLogger//WorkLogger//EN",
        "CALSCALE:GREGORIAN",
    ]
    for index, row in enumerate(rows):
        event_lines = _event_lines(row, index=index, dtstamp=dtstamp)
        if event_lines:
            lines.extend(event_lines)
    lines.append("END:VCALENDAR")
    folded: list[str] = []
    for line in lines:
        folded.extend(_fold_ics_line(line))
    return "\r\n".join(folded) + "\r\n"


def _event_lines(row: WorkLog, *, index: int, dtstamp: str) -> list[str]:
    if not row.has_times or row.is_leave:
        return []
    assert row.start_time is not None
    assert row.end_time is not None
    datetimes = TimeRange(row.start_time, row.end_time).as_datetimes(row.day)
    if datetimes is None:
        return []
    start_dt, end_dt = datetimes
    start_stamp = start_dt.strftime("%Y%m%dT%H%M%S")
    end_stamp = end_dt.strftime("%Y%m%dT%H%M%S")
    note = row.note or ""
    summary_note = _summary_note(note)
    summary = f"Work {row.raw_hours():.1f}h"
    if summary_note:
        summary = f"{summary} - {summary_note[:60]}"
    return [
        "BEGIN:VEVENT",
        f"UID:worklogger-{row.day.isoformat()}-{start_stamp}-{index}@worklogger",
        f"DTSTAMP:{dtstamp}",
        f"DTSTART:{start_stamp}",
        f"DTEND:{end_stamp}",
        f"SUMMARY:{_escape_ics_text(summary)}",
        f"DESCRIPTION:{_escape_ics_text(note[:500])}",
        "END:VEVENT",
    ]


def _summary_note(note: str) -> str:
    return re.sub(r"[\r\n]+", " ", str(note)).strip()


def _escape_ics_text(value: str) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\r", "\\n")
        .replace("\n", "\\n")
    )


def _fold_ics_line(line: str) -> list[str]:
    if len(line.encode("utf-8")) <= _LINE_LIMIT_BYTES:
        return [line]

    folded: list[str] = []
    current = ""
    current_bytes = 0
    for char in line:
        char_bytes = len(char.encode("utf-8"))
        if current and current_bytes + char_bytes > _LINE_LIMIT_BYTES:
            folded.append(current)
            current = " " + char
            current_bytes = 1 + char_bytes
        else:
            current += char
            current_bytes += char_bytes
    if current:
        folded.append(current)
    return folded
