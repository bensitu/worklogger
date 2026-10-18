"""Manual record construction and conflict-aware persistence."""

from dataclasses import dataclass, replace
from datetime import date, tzinfo

from worklogger.app.entry_selection import EntrySelectionResolver
from worklogger.domain.projects.models import WorkContext
from worklogger.domain.shared.errors import ConflictError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.content import require_entry_content
from worklogger.domain.worklog.entry_repository import TimeEntryRepository
from worklogger.domain.worklog.models import EntryCategory, WorkLog, WorkModeValue
from worklogger.domain.worklog.rules import normalize_work_log, parse_time, shift_datetimes


@dataclass(frozen=True)
class ManualEntryWriter:
    user_id: int
    repository: TimeEntryRepository
    local_timezone: tzinfo
    selection: EntrySelectionResolver

    def save(self, day: date, start: str, end: str, entry_type: str, content: str,
             original: WorkLog | None = None, *, context: WorkContext | None = None,
             work_mode: WorkModeValue | None = None) -> Result[WorkLog]:
        if original is not None and original.user_id != self.user_id:
            raise ValueError("worklog_entry_conflict")
        definition = self.selection.resolve_entry_type(entry_type, original.entry_type if original else None)
        arrangement = self.selection.resolve_work_mode(work_mode, original.work_mode if original else None)
        if original and original.break_hours and definition.category != original.entry_type.category:
            raise ValueError("historical_break_placement_required")
        if context is None:
            context = original.context if original and definition.category == EntryCategory.WORK else WorkContext()
        association = self.selection.resolve_context(context, original.context if original else None)
        if (original and original.is_leave and not original.has_times and not start.strip()
                and not end.strip() and definition.category == EntryCategory.LEAVE):
            record = normalize_work_log(replace(original, note=require_entry_content(content),
                entry_type=definition, context=association, work_mode=arrangement))
            return Result.success(self.repository.save_entry(record))
        start_time, end_time = parse_time(start), parse_time(end)
        if not start_time or not end_time:
            raise ValueError("time_range_incomplete")
        if original and (original.day, original.start_time, original.end_time) == (day, start_time, end_time):
            timestamps = original.started_at, original.ended_at
        else:
            timestamps = shift_datetimes(day, start_time, end_time, self.local_timezone)
        record = normalize_work_log(WorkLog(
            self.user_id, day, start_time, end_time,
            original.break_hours if original else 0, require_entry_content(content), definition,
            started_at=timestamps[0], ended_at=timestamps[1], id=original.id if original else None,
            revision=original.revision if original else 0, capture_id=original.capture_id if original else None,
            context=association, work_mode=arrangement,
        ))
        try:
            return Result.success(self.repository.save_entry(record, remember_work_mode=original is None))
        except ValueError as error:
            if str(error) != "worklog_entry_overlap" or not getattr(self.repository, "changes_available", False):
                raise
            plan = self.repository.preview_replacement(self.user_id, record, original)
            if not plan.conflicts:
                raise
            return Result.failure(ConflictError("worklog_entry_overlap", "worklog_entry_overlap", {"replacement": plan}))
