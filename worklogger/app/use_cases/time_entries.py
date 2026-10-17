"""Time-entry editing and persistent automatic recording."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone, tzinfo
import math
from uuid import uuid4
from collections.abc import Callable
from worklogger.config.constants import LAST_USED_WORK_MODE_SETTING_KEY

from worklogger.domain.settings.repositories import SettingsRepository
from worklogger.domain.calendar.repositories import CalendarEventRepository
from worklogger.domain.calendar.models import CalendarEvent
from worklogger.domain.shared.errors import ConflictError, ValidationError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.entry_repository import TimeEntryRepository
from worklogger.domain.worklog.editing import EntryChangeInfo
from worklogger.domain.worklog.search import EntryCursor, EntryFilter, EntryPage
from worklogger.domain.worklog.timer_state import EntryTimer, decode_timer, encode_timer, timer_payload
from worklogger.domain.worklog.content import require_entry_content
from worklogger.domain.worklog.rules import wall_interval, wall_position
from worklogger.domain.worklog.models import CustomEntryType, WorkLog, EntryType, EntryCategory, WorkMode
from worklogger.domain.worklog.rules import entry_interval, normalize_work_log, parse_time, shift_datetimes
from worklogger.app.ports import EntryTypeOperations, ProjectOperations
from worklogger.app.time_entry_state import RecordingState
from worklogger.app.use_cases._errors import infrastructure_failure
from worklogger.domain.projects.models import WorkContext
from worklogger.domain.worklog.replacement import EntryReplacement


FIXED_BREAK_CAPTURE_PREFIX = "fixed-break:"


class TimeEntryService:
    def __init__(self, *, user_id: int, repository: TimeEntryRepository, settings: SettingsRepository,
                 local_timezone: tzinfo, clock: Callable[[], datetime] | None = None,
                 calendar_events: CalendarEventRepository | None = None,
                 entry_types: EntryTypeOperations | None = None,
                 projects: ProjectOperations | None = None,
                 initial_state: RecordingState | None = None) -> None:
        self.user_id = user_id
        self.repository = repository
        self.settings = settings
        self.calendar_events = calendar_events
        self.entry_types = entry_types
        self.projects = projects
        self.local_timezone = local_timezone
        self._clock = clock or (lambda: datetime.now().astimezone())
        self.timer: EntryTimer | None = None
        self._timer_raw: str | None = None
        self.last_error = None
        self.restore_failed = False
        if initial_state is None:
            self._restore()
        else:
            self.apply_state(initial_state)

    def now(self) -> datetime:
        return self._clock().astimezone(self.local_timezone)

    def default_work_mode(self) -> WorkMode | None:
        try:
            raw = self.settings.get(self.user_id, LAST_USED_WORK_MODE_SETTING_KEY)
            return WorkMode(raw) if raw else None
        except ValueError:
            return None
        except Exception as error:
            infrastructure_failure("work_mode_load_failed", error, logger_name=__name__)
            return None

    def snapshot_state(self) -> RecordingState:
        return RecordingState(self.timer, self._timer_raw, self.restore_failed, self.last_error)

    def apply_state(self, state: RecordingState) -> None:
        self.timer = state.timer
        self._timer_raw = state.persisted_timer
        self.restore_failed = state.restore_failed
        self.last_error = state.error

    def new_session(self, state: RecordingState) -> TimeEntryService:
        return TimeEntryService(user_id=self.user_id, repository=self.repository,
            settings=self.settings, local_timezone=self.local_timezone, clock=self._clock,
            calendar_events=self.calendar_events, entry_types=self.entry_types,
            projects=self.projects, initial_state=state)

    @property
    def events_deletable(self) -> bool:
        return self.calendar_events is not None

    def _restore(self) -> None:
        try:
            self._timer_raw = self.settings.get(self.user_id, "time_entry_timer")
            if self._timer_raw:
                timer = decode_timer(self._timer_raw)
                if self.projects is not None:
                    self.projects.resolve(timer.context, timer.context)
                self.timer = timer
            else:
                if self.settings.get(self.user_id, "previous_auto_record_state"):
                    raise ValueError("auto_record_restore_failed")
        except Exception as error:
            self.restore_failed = True
            self.last_error = infrastructure_failure("auto_record_restore_failed", error, logger_name=__name__)


    def _persist(self, timer: EntryTimer | None) -> None:
        raw = encode_timer(timer)
        self.repository.change_timer(self.user_id, self._timer_raw, raw)
        self.timer, self._timer_raw = timer, raw

    def _run(self, operation, *, error_code="worklog_save_failed"):
        try:
            value = operation()
            if isinstance(value, Result):
                self.last_error = value.error
                return value
            self.last_error = None
            return Result.success(value)
        except ValueError as exc:
            code = str(exc)
            if code == "auto_record_restore_failed":
                self.restore_failed = True
            error_type = ConflictError if code in {"worklog_entry_conflict", "time_entry_timer_conflict", "record_change_conflict"} else ValidationError
            self.last_error = error_type(code, code)
        except Exception as error:
            self.last_error = infrastructure_failure(error_code, error, logger_name=__name__)
        return Result.failure(self.last_error)

    def list_for_day(self, day: date) -> Result[tuple[WorkLog, ...]]:
        return self._run(lambda: self.repository.list_for_day(self.user_id, day))

    @property
    def search_available(self) -> bool:
        return callable(getattr(self.repository, "search_entries", None))

    def search(self, criteria: EntryFilter, *, cursor: EntryCursor | None = None) -> Result[EntryPage]:
        if not self.search_available:
            return Result.failure(ValidationError("record_search_unavailable", "record_search_unavailable"))
        try:
            return Result.success(self.repository.search_entries(self.user_id, criteria, cursor=cursor))
        except ValueError:
            return Result.failure(ValidationError("record_search_invalid", "record_search_invalid"))
        except Exception as error:
            return Result.failure(infrastructure_failure("record_search_failed", error, logger_name=__name__))

    @property
    def changes_available(self) -> bool:
        return bool(getattr(self.repository, "changes_available", False))

    def latest_change(self) -> Result[EntryChangeInfo | None]:
        return self._run(lambda: self.repository.latest_change(self.user_id), error_code="record_change_failed")

    def split(self, record: WorkLog, first_minutes: int) -> Result[tuple[WorkLog, ...]]:
        return self._run(lambda: self.repository.split_entry(self.user_id, record, first_minutes), error_code="record_change_failed")

    def split_at(self, record: WorkLog, cut: datetime) -> Result[tuple[WorkLog, ...]]:
        return self._run(lambda: self.repository.split_entry_at(self.user_id, record, cut), error_code="record_change_failed")

    def replace_overlap(self, plan: EntryReplacement, *, keep_outside: bool) -> Result[WorkLog]:
        def save():
            record = plan.incoming
            if record.user_id != self.user_id:
                raise ValueError("worklog_entry_conflict")
            self._resolve_type(record.entry_type.value, plan.original.entry_type if plan.original else None)
            self._resolve_context(record.context, plan.original.context if plan.original else None)
            return self.repository.replace_overlap(self.user_id, plan, keep_outside=keep_outside,
                                                   remember_work_mode=plan.original is None)
        return self._run(save)

    def merge(self, left: WorkLog, right: WorkLog) -> Result[WorkLog]:
        return self._run(lambda: self.repository.merge_entries(self.user_id, left, right), error_code="record_change_failed")

    def convert_break(self, record: WorkLog, first_minutes: int) -> Result[tuple[WorkLog, ...]]:
        return self._run(lambda: self.repository.convert_historical_break(self.user_id, record, first_minutes), error_code="record_change_failed")

    def undo(self, change_id: int) -> Result[tuple[WorkLog, ...]]:
        return self._run(lambda: self.repository.undo_change(self.user_id, change_id), error_code="record_change_failed")

    def associate(self, records: tuple[WorkLog, ...], context: WorkContext) -> Result[tuple[WorkLog, ...]]:
        return self._run(lambda: self.repository.associate_entries(self.user_id, records, context), error_code="record_change_failed")

    def get_entry(self, entry_id: int) -> Result[WorkLog]:
        def load():
            record = self.repository.get_entry(self.user_id, entry_id)
            if record is None:
                raise ValueError("worklog_entry_conflict")
            return record
        return self._run(load)

    def save_manual(self, day: date, start: str, end: str, entry_type: str, content: str,
                    original: WorkLog | None = None, *, context: WorkContext | None = None,
                    work_mode: WorkMode | None = None) -> Result[WorkLog]:
        def save():
            if original and original.user_id != self.user_id:
                raise ValueError("worklog_entry_conflict")
            definition = self._resolve_type(entry_type, original.entry_type if original else None)
            if original and original.break_hours and definition.category != original.entry_type.category:
                raise ValueError("historical_break_placement_required")
            association = self._resolve_context(context if context is not None else original.context if original and definition.category == EntryCategory.WORK else WorkContext(),
                                                original.context if original else None)
            if original and original.is_leave and not original.has_times and not start.strip() and not end.strip() and replace(original, entry_type=definition).is_leave:
                return self.repository.save_entry(normalize_work_log(replace(original, note=require_entry_content(content),
                    entry_type=definition, context=association, work_mode=work_mode)))
            start_time, end_time = parse_time(start), parse_time(end)
            if not start_time or not end_time:
                raise ValueError("time_range_incomplete")
            if original and original.user_id != self.user_id:
                raise ValueError("worklog_entry_conflict")
            timestamps = (original.started_at, original.ended_at) if original and (
                original.day, original.start_time, original.end_time) == (day, start_time, end_time) else shift_datetimes(day, start_time, end_time, self.local_timezone)
            record = normalize_work_log(WorkLog(self.user_id, day, start_time, end_time,
                original.break_hours if original else 0, require_entry_content(content), definition,
                started_at=timestamps[0], ended_at=timestamps[1], id=original.id if original else None,
                revision=original.revision if original else 0, capture_id=original.capture_id if original else None,
                context=association, work_mode=work_mode))
            try:
                return self.repository.save_entry(record, remember_work_mode=original is None)
            except ValueError as error:
                if str(error) != "worklog_entry_overlap" or not self.changes_available:
                    raise
                plan = self.repository.preview_replacement(self.user_id, record, original)
                if not plan.conflicts:
                    raise
                return Result.failure(ConflictError("worklog_entry_overlap", "worklog_entry_overlap", {"replacement": plan}))
        return self._run(save)

    def _resolve_type(self, value: str, original=None):
        if self.entry_types is not None:
            return self.entry_types.resolve(value, original)
        if isinstance(original, CustomEntryType) and original.value == value:
            return original
        definition = EntryType(value)
        if definition.is_legacy and definition != original:
            raise ValueError("entry_type_unavailable")
        return definition

    def validate_selection(self, entry_type: str, work_mode: WorkMode | None, context: WorkContext,
                           original: WorkLog | None = None, *, automatic: bool = False
                           ) -> Result[tuple[EntryType | CustomEntryType, WorkMode | None, WorkContext]]:
        def resolve():
            if original is not None and original.user_id != self.user_id:
                raise ValueError("worklog_entry_conflict")
            definition = self._resolve_type(entry_type, original.entry_type if original else None)
            try:
                arrangement = WorkMode(work_mode) if work_mode is not None else None
            except (ValueError, TypeError):
                raise ValueError("work_mode_invalid") from None
            if definition.category != EntryCategory.WORK and (arrangement is not None or context != WorkContext()):
                raise ValueError("entry_classification_invalid")
            if automatic and definition.category != EntryCategory.WORK:
                raise ValueError("auto_record_work_required")
            return definition, arrangement, self._resolve_context(context, original.context if original else None)
        return self._run(resolve, error_code="entry_types_load_failed")

    def _resolve_context(self, context, original=None):
        if not isinstance(context, WorkContext):
            raise ValueError("work_context_invalid")
        if self.projects is None:
            if context.project_id is not None:
                raise ValueError("project_unavailable")
            return context
        return self.projects.resolve(context, original)

    def delete(self, record: WorkLog) -> Result[None]:
        return self._run(lambda: self.repository.delete_entry(self.user_id, record.id, record.revision))

    def delete_event(self, event: CalendarEvent) -> Result[None]:
        return self._run(lambda: self.calendar_events.remove(self.user_id, event))

    def start(self, entry_type: str, content: str, *, now: datetime | None = None,
              break_entry: WorkLog | None = None, context: WorkContext | None = None,
              work_mode: WorkMode | None = None) -> Result[EntryTimer]:
        def start():
            if self.restore_failed:
                raise ValueError("auto_record_restore_failed")
            if self.timer:
                raise ValueError("auto_record_already_active")
            definition = self._resolve_type(entry_type)
            if definition.category != EntryCategory.WORK:
                raise ValueError("auto_record_work_required")
            try:
                arrangement = WorkMode(work_mode) if work_mode is not None else None
            except (TypeError, ValueError):
                raise ValueError("work_mode_invalid") from None
            moment = now or self.now()
            if not isinstance(moment, datetime) or moment.tzinfo is None:
                raise ValueError("time_range_invalid")
            moment = moment.astimezone(self.local_timezone)
            instant = moment.astimezone(timezone.utc)
            break_interval = None
            if break_entry is not None:
                break_interval = entry_interval(break_entry)
                if (break_entry.user_id != self.user_id or break_entry.id is None or not self._is_fixed_break(break_entry)
                    or break_interval is None or not break_interval[0] <= instant < break_interval[1]):
                    raise ValueError("worklog_entry_conflict")
            active_break = None
            for ordinal in range(max(date.min.toordinal(), moment.date().toordinal() - 3),
                                 min(date.max.toordinal(), moment.date().toordinal() + 3) + 1):
                day = date.fromordinal(ordinal)
                for record in self.repository.list_for_day(self.user_id, day):
                    if break_entry is not None and record.id == break_entry.id:
                        if record != break_entry:
                            raise ValueError("worklog_entry_conflict")
                        continue
                    captured = record.started_at is not None and record.ended_at is not None
                    interval = entry_interval(record) if captured else wall_interval(record)
                    point = instant if captured else wall_position(moment)
                    if (record.day == moment.date() and record.is_leave and not record.has_times) or (interval and interval[0] <= point < interval[1]):
                        if break_entry is None and self._is_fixed_break(record):
                            active_break = record
                        else:
                            raise ValueError("worklog_entry_overlap")
            if active_break is not None:
                return Result.failure(ConflictError("fixed_break_active", "fixed_break_active", {"break_entry": active_break}))
            timer = EntryTimer(uuid4().hex, moment, definition, require_entry_content(content),
                               context=self._resolve_context(context or WorkContext()), work_mode=arrangement)
            if break_entry is None:
                self._persist(timer)
            else:
                raw = encode_timer(timer)
                change = (self._timer_raw, raw)
                if instant == break_interval[0]:
                    self.repository.delete_entry(self.user_id, break_entry.id, break_entry.revision, timer_change=change)
                else:
                    self.repository.save_entry(replace(break_entry, end_time=moment.strftime("%H:%M"), ended_at=moment), timer_change=change)
                self.timer, self._timer_raw = timer, raw
            return timer
        return self._run(start)

    @staticmethod
    def _is_fixed_break(record: WorkLog) -> bool:
        return record.entry_type == EntryType.BREAK and bool(record.capture_id and record.capture_id.startswith(FIXED_BREAK_CAPTURE_PREFIX))

    def save_content(self, content: str, completed: WorkLog | None = None) -> Result[WorkLog | EntryTimer]:
        def save():
            if self.timer:
                timer = replace(self.timer, content=require_entry_content(content))
                self._persist(timer)
                return timer
            if completed is None:
                raise ValueError("auto_record_not_started")
            return self.repository.save_entry(replace(completed, note=require_entry_content(content)))
        return self._run(save)

    def _finish(self, end: datetime, content: str, next_timer: EntryTimer | None) -> WorkLog:
        timer = self.timer
        if timer is None:
            raise ValueError("auto_record_not_started")
        record = normalize_work_log(WorkLog(self.user_id, timer.started_at.date(), timer.started_at.strftime("%H:%M"),
            end.strftime("%H:%M"), timer.legacy_break_hours, require_entry_content(content), timer.entry_type,
            started_at=timer.started_at, ended_at=end, capture_id=timer.capture_id,
            context=timer.context if timer.entry_type.category == EntryCategory.WORK else WorkContext(), work_mode=timer.work_mode))
        raw = encode_timer(next_timer)
        saved = self.repository.save_entry(record, timer_change=(self._timer_raw, raw), remember_work_mode=True)
        self.timer, self._timer_raw = next_timer, raw
        return saved

    def finish(self, content: str, *, now: datetime | None = None) -> Result[WorkLog]:
        def finish():
            if self.timer is None:
                raise ValueError("auto_record_not_started")
            return self._finish(self.timer.pending_end or now or self.now(), content, None)
        return self._run(finish)

    def take_break(self, hours: float, content: str, *, now: datetime | None = None) -> Result[WorkLog]:
        def take_break():
            if self.restore_failed:
                raise ValueError("auto_record_restore_failed")
            if self.timer is not None:
                raise ValueError("auto_record_already_active")
            if not math.isfinite(hours) or not 0 < hours <= 4:
                raise ValueError("fixed_break_hours_invalid")
            moment = now or self.now()
            if not isinstance(moment, datetime) or moment.tzinfo is None:
                raise ValueError("time_range_invalid")
            moment = moment.astimezone(self.local_timezone)
            deadline = (moment.astimezone(timezone.utc) + timedelta(hours=hours)).astimezone(self.local_timezone)
            record = normalize_work_log(WorkLog(self.user_id, moment.date(), moment.strftime("%H:%M"),
                deadline.strftime("%H:%M"), 0, require_entry_content(content), EntryType.BREAK,
                started_at=moment, ended_at=deadline, capture_id=FIXED_BREAK_CAPTURE_PREFIX + uuid4().hex))
            return self.repository.save_entry(record, timer_change=(self._timer_raw, None))
        return self._run(take_break)

    def resume(self, content: str, *, at_deadline: bool = False, now: datetime | None = None) -> Result[WorkLog]:
        def resume():
            if self.timer is None or self.timer.break_until is None:
                raise ValueError("auto_record_break_not_active")
            moment = self.timer.break_until if at_deadline else min(now or self.now(), self.timer.break_until)
            next_timer = EntryTimer(uuid4().hex, moment, self.timer.resume_type, self.timer.resume_content,
                context=self.timer.context,
                work_mode={EntryType.REMOTE: WorkMode.REMOTE, EntryType.BUSINESS_TRIP: WorkMode.BUSINESS_TRIP}.get(self.timer.resume_type))
            return self._finish(moment, content, next_timer)
        return self._run(resume)

    def advance(self) -> Result[WorkLog | None]:
        if self.timer and self.timer.break_until and self.now() >= self.timer.break_until:
            return self.resume(self.timer.content, at_deadline=True)
        return Result.success(None)

    def discard_timer(self) -> Result[None]:
        def discard():
            if self.restore_failed and self._timer_raw is None:
                current = self.settings.get(self.user_id, "time_entry_timer")
                if current:
                    try:
                        timer_payload(current)
                    except ValueError:
                        self._timer_raw = current
                    else:
                        raise ValueError("time_entry_timer_conflict")
            self._persist(None)
        result = self._run(discard)
        if result.ok:
            self.restore_failed = False
        return result
