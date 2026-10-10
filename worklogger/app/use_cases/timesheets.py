"""Account-owned timesheet exports that never save or replace report drafts."""

from datetime import datetime
from pathlib import Path
from collections.abc import Mapping
from worklogger.app.ports import TimesheetExporter

from worklogger.app.use_cases.user_profile import profile_display_name
from worklogger.domain.reporting.timesheets import Timesheet, MAX_TIMESHEET_ENTRIES
from worklogger.domain.shared.errors import InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result


class ExportTimesheetHandler:
    def __init__(self, *, records, exporters: Mapping[str, TimesheetExporter], profiles=None, clock=None):
        self._records, self._exporters, self._profiles = records, exporters, profiles
        self._clock = clock or (lambda: datetime.now().astimezone())

    def handle(self, user_id, start, end, destination: Path, *, format="xlsx", standard_hours=8):
        if format not in self._exporters:
            return Result.failure(ValidationError("timesheet_format_invalid", "timesheet_format_invalid"))
        try:
            if end < start or (end - start).days > 366:
                raise ValueError("timesheet_invalid")
        except (TypeError, ValueError):
            return Result.failure(ValidationError("timesheet_invalid", "timesheet_invalid"))
        try:
            reader = getattr(self._records, "list_entries_range", None)
            rows = reader(user_id, start, end, limit=MAX_TIMESHEET_ENTRIES + 1) if reader else self._records.list_range(user_id, start, end)
            entries = tuple(entry for record in rows for entry in (record.entries or (record,)) if not entry.is_note_only)
            author = profile_display_name(self._profiles, user_id)
        except Exception:
            return Result.failure(InfrastructureError("timesheet_load_failed", "timesheet_load_failed"))
        try:
            if any(entry.user_id != user_id for entry in entries):
                raise ValueError("timesheet_invalid")
            snapshot = Timesheet(start, end, author, self._clock(), float(standard_hours), entries)
        except (TypeError, ValueError) as error:
            code = "timesheet_too_large" if str(error) == "timesheet_too_large" else "timesheet_invalid"
            return Result.failure(ValidationError(code, code))
        except Exception:
            return Result.failure(InfrastructureError("timesheet_load_failed", "timesheet_load_failed"))
        path = Path(destination)
        if path.suffix.lower() != "." + format:
            path = path.with_name(path.name + "." + format)
        return self._exporters[format].export_timesheet(path, snapshot)
