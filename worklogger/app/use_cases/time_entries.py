"""Time-entry editing and persistent automatic recording."""

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta, timezone, tzinfo
import hashlib
import json
import math
from uuid import uuid4
from collections.abc import Callable
from worklogger.config.constants import MAX_SHIFT_HOURS

from worklogger.domain.settings.repositories import SettingsRepository
from worklogger.domain.calendar.repositories import CalendarEventRepository
from worklogger.domain.shared.errors import ConflictError, InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.entry_repository import TimeEntryRepository
from worklogger.domain.worklog.models import WorkLog, WorkType
from worklogger.domain.worklog.rules import entry_interval, normalize_work_log, parse_time, shift_datetimes, timestamp_span_hours


FIXED_BREAK_CAPTURE_PREFIX = "fixed-break:"


@dataclass(frozen=True)
class EntryTimer:
    capture_id: str
    started_at: datetime
    work_type: WorkType
    content: str = ""
    break_until: datetime | None = None
    resume_type: WorkType | None = None
    resume_content: str = ""
    legacy_break_hours: float = 0.0
    pending_end: datetime | None = None


class TimeEntryService:
    def __init__(self, *, user_id: int, repository: TimeEntryRepository, settings: SettingsRepository,
                 local_timezone: tzinfo, clock: Callable[[], datetime] | None = None,
                 calendar_events: CalendarEventRepository | None = None) -> None:
        self.user_id = user_id
        self.repository = repository
        self.settings = settings
        self.calendar_events = calendar_events
        self.local_timezone = local_timezone
        self._clock = clock or (lambda: datetime.now().astimezone())
        self.timer: EntryTimer | None = None
        self._timer_raw: str | None = None
        self.last_error = None
        self.restore_failed = False
        self._restore()

    def now(self) -> datetime:
        return self._clock().astimezone(self.local_timezone)

    @property
    def events_deletable(self) -> bool:
        return self.calendar_events is not None

    def _restore(self) -> None:
        try:
            self._timer_raw = self.settings.get(self.user_id, "time_entry_timer")
            if self._timer_raw:
                if len(self._timer_raw) > 128 * 1024:
                    raise ValueError("auto_record_restore_failed")
                data = json.loads(self._timer_raw)
                for key in ("started_at", "break_until", "pending_end"):
                    data[key] = datetime.fromisoformat(data[key]) if data.get(key) else None
                data["work_type"] = WorkType(data["work_type"])
                data["resume_type"] = WorkType(data["resume_type"]) if data.get("resume_type") else None
                timer = EntryTimer(**data)
                if (not isinstance(timer.capture_id, str) or not timer.capture_id or len(timer.capture_id) > 64 or timer.started_at is None
                    or any(moment.tzinfo is None for moment in (timer.started_at, timer.break_until, timer.pending_end) if moment)
                    or not math.isfinite(timer.legacy_break_hours) or not 0 <= timer.legacy_break_hours <= MAX_SHIFT_HOURS
                    or bool(timer.break_until) != bool(timer.resume_type)):
                    raise ValueError("auto_record_restore_failed")
                self._content(timer.content)
                self._content(timer.resume_content)
                if timer.break_until and not 0 < timestamp_span_hours(timer.started_at, timer.break_until) <= 4:
                    raise ValueError("auto_record_restore_failed")
                if timer.break_until and (timer.work_type != WorkType.BREAK or timer.resume_type == WorkType.BREAK or timer.pending_end):
                    raise ValueError("auto_record_restore_failed")
                self.timer = timer
            else:
                previous = self.settings.get(self.user_id, "previous_auto_record_state")
                if previous:
                    self._restore_previous(previous)
        except Exception:
            self.restore_failed = True
            self.last_error = InfrastructureError("auto_record_restore_failed", "auto_record_restore_failed")

    def _restore_previous(self, raw: str) -> None:
        if len(raw) > 1024 * 1024:
            raise ValueError("auto_record_restore_failed")
        data = json.loads(raw)
        start = datetime.fromisoformat(data["started_at"]) if data.get("started_at") else datetime.combine(
            date.fromisoformat(data["day"]), datetime.strptime(data["start_time"], "%H:%M").time(), self.local_timezone)
        end = datetime.fromisoformat(data["ended_at"]) if data.get("ended_at") else None
        if data.get("pending_save") and end is None:
            end = shift_datetimes(start.date(), data["start_time"], data["end_time"], self.local_timezone)[1]
        deduction = float(data.get("break_hours", 0))
        if data.get("break_active") and data.get("break_started_at"):
            deduction = max(0, timestamp_span_hours(datetime.fromisoformat(data["break_started_at"]), self.now()))
        timer = EntryTimer(hashlib.sha256((str(self.user_id) + raw).encode()).hexdigest(), start,
                           WorkType(data["work_type"]), self._content(data.get("note", "")),
                           legacy_break_hours=deduction, pending_end=end)
        if not math.isfinite(deduction) or not 0 <= deduction <= MAX_SHIFT_HOURS or start.tzinfo is None:
            raise ValueError("auto_record_restore_failed")
        self._persist(timer)

    @staticmethod
    def _encode(timer: EntryTimer | None) -> str | None:
        if timer is None:
            return None
        data = asdict(timer)
        for key in ("started_at", "break_until", "pending_end"):
            data[key] = data[key].isoformat() if data[key] else None
        return json.dumps(data, allow_nan=False, ensure_ascii=False)

    def _persist(self, timer: EntryTimer | None) -> None:
        raw = self._encode(timer)
        self.repository.change_timer(self.user_id, self._timer_raw, raw)
        self.timer, self._timer_raw = timer, raw

    @staticmethod
    def _content(content: str) -> str:
        if not isinstance(content, str) or len(content) > 16000:
            raise ValueError("time_entry_content_too_long")
        return content

    def _run(self, operation):
        try:
            value = operation()
            if isinstance(value, Result):
                self.last_error = value.error
                return value
            self.last_error = None
            return Result.success(value)
        except ValueError as exc:
            code = str(exc)
            error_type = ConflictError if code in {"worklog_entry_conflict", "time_entry_timer_conflict"} else ValidationError
            self.last_error = error_type(code, code)
        except Exception:
            self.last_error = InfrastructureError("worklog_save_failed", "worklog_save_failed")
        return Result.failure(self.last_error)

    def list_for_day(self, day: date) -> Result[tuple[WorkLog, ...]]:
        return self._run(lambda: self.repository.list_for_day(self.user_id, day))

    def get_entry(self, entry_id: int) -> Result[WorkLog]:
        def load():
            record = self.repository.get_entry(self.user_id, entry_id)
            if record is None:
                raise ValueError("worklog_entry_conflict")
            return record
        return self._run(load)

    def save_manual(self, day: date, start: str, end: str, work_type: str, content: str,
                    original: WorkLog | None = None) -> Result[WorkLog]:
        def save():
            if original and not original.has_times and not start.strip() and not end.strip() and WorkType(work_type) in {
                WorkType.PAID_LEAVE, WorkType.COMP_LEAVE, WorkType.SICK_LEAVE}:
                return self.repository.save_entry(replace(original, note=self._content(content), work_type=WorkType(work_type)))
            start_time, end_time = parse_time(start), parse_time(end)
            if not start_time or not end_time:
                raise ValueError("time_range_incomplete")
            if original and original.user_id != self.user_id:
                raise ValueError("worklog_entry_conflict")
            timestamps = (original.started_at, original.ended_at) if original and (
                original.day, original.start_time, original.end_time) == (day, start_time, end_time) else shift_datetimes(day, start_time, end_time, self.local_timezone)
            record = normalize_work_log(WorkLog(self.user_id, day, start_time, end_time,
                original.break_hours if original else 0, self._content(content), WorkType(work_type),
                started_at=timestamps[0], ended_at=timestamps[1], id=original.id if original else None,
                revision=original.revision if original else 0, capture_id=original.capture_id if original else None))
            return self.repository.save_entry(record)
        return self._run(save)

    def delete(self, record: WorkLog) -> Result[None]:
        return self._run(lambda: self.repository.delete_entry(self.user_id, record.id, record.revision))

    def delete_event(self, event) -> Result[None]:
        return self._run(lambda: self.calendar_events.remove(self.user_id, event))

    def start(self, work_type: str, content: str, *, now: datetime | None = None,
              break_entry: WorkLog | None = None) -> Result[EntryTimer]:
        def start():
            if self.restore_failed:
                raise ValueError("auto_record_restore_failed")
            if self.timer:
                raise ValueError("auto_record_already_active")
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
            for day in (moment.date() - timedelta(days=1), moment.date()):
                for record in self.repository.list_for_day(self.user_id, day):
                    if break_entry is not None and record.id == break_entry.id:
                        if record != break_entry:
                            raise ValueError("worklog_entry_conflict")
                        continue
                    interval = entry_interval(record)
                    if (record.day == moment.date() and record.is_leave and not record.has_times) or (interval and interval[0] <= instant < interval[1]):
                        if break_entry is None and self._is_fixed_break(record):
                            active_break = record
                        else:
                            raise ValueError("worklog_entry_overlap")
            if active_break is not None:
                return Result.failure(ConflictError("fixed_break_active", "fixed_break_active", {"break_entry": active_break}))
            timer = EntryTimer(uuid4().hex, moment, WorkType(work_type), self._content(content))
            if break_entry is None:
                self._persist(timer)
            else:
                raw = self._encode(timer)
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
        return record.work_type == WorkType.BREAK and bool(record.capture_id and record.capture_id.startswith(FIXED_BREAK_CAPTURE_PREFIX))

    def save_content(self, content: str, completed: WorkLog | None = None) -> Result[WorkLog | EntryTimer]:
        def save():
            if self.timer:
                timer = replace(self.timer, content=self._content(content))
                self._persist(timer)
                return timer
            if completed is None:
                raise ValueError("auto_record_not_started")
            return self.repository.save_entry(replace(completed, note=self._content(content)))
        return self._run(save)

    def _finish(self, end: datetime, content: str, next_timer: EntryTimer | None) -> WorkLog:
        timer = self.timer
        if timer is None:
            raise ValueError("auto_record_not_started")
        record = normalize_work_log(WorkLog(self.user_id, timer.started_at.date(), timer.started_at.strftime("%H:%M"),
            end.strftime("%H:%M"), timer.legacy_break_hours, self._content(content), timer.work_type,
            started_at=timer.started_at, ended_at=end, capture_id=timer.capture_id))
        raw = self._encode(next_timer)
        saved = self.repository.save_entry(record, timer_change=(self._timer_raw, raw))
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
                raise ValueError("break_hours_too_long")
            moment = now or self.now()
            if not isinstance(moment, datetime) or moment.tzinfo is None:
                raise ValueError("time_range_invalid")
            moment = moment.astimezone(self.local_timezone)
            deadline = (moment.astimezone(timezone.utc) + timedelta(hours=hours)).astimezone(self.local_timezone)
            record = normalize_work_log(WorkLog(self.user_id, moment.date(), moment.strftime("%H:%M"),
                deadline.strftime("%H:%M"), 0, self._content(content), WorkType.BREAK,
                started_at=moment, ended_at=deadline, capture_id=FIXED_BREAK_CAPTURE_PREFIX + uuid4().hex))
            return self.repository.save_entry(record, timer_change=(self._timer_raw, None))
        return self._run(take_break)

    def resume(self, content: str, *, at_deadline: bool = False, now: datetime | None = None) -> Result[WorkLog]:
        def resume():
            if self.timer is None or self.timer.break_until is None:
                raise ValueError("auto_record_break_not_active")
            moment = self.timer.break_until if at_deadline else min(now or self.now(), self.timer.break_until)
            next_timer = EntryTimer(uuid4().hex, moment, self.timer.resume_type, self.timer.resume_content)
            return self._finish(moment, content, next_timer)
        return self._run(resume)

    def advance(self) -> Result[WorkLog | None]:
        if self.timer and self.timer.break_until and self.now() >= self.timer.break_until:
            return self.resume(self.timer.content, at_deadline=True)
        return Result.success(None)

    def discard_timer(self) -> Result[None]:
        result = self._run(lambda: self._persist(None))
        if result.ok:
            self.restore_failed = False
        return result
