"""Auto-record presentation state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta, timezone
import json
import math
from worklogger.config.constants import MAX_SHIFT_HOURS

from worklogger.domain.shared.errors import InfrastructureError, ValidationError
from worklogger.domain.settings.repositories import SettingsRepository
from worklogger.domain.notes.repositories import DailyNoteRepository
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkType
from worklogger.domain.worklog.rules import normalize_work_type, parse_time, normalize_work_log
from worklogger.domain.worklog.models import WorkLog


Clock = Callable[[], datetime]
AUTO_RECORD_STATE_SETTING_KEY = "auto_record_state"


@dataclass(frozen=True)
class AutoRecordEntryDraft:
    day: date
    start_time: str | None
    end_time: str | None
    break_hours: float
    note: str
    work_type: str


@dataclass(frozen=True)
class AutoRecordState:
    day: date | None
    start_time: str | None
    end_time: str | None
    break_hours: float
    note: str
    work_type: str
    active: bool = False
    break_active: bool = False
    break_started_at: datetime | None = None
    started_at: datetime | None = None
    pending_save: bool = False
    ended_at: datetime | None = None
    expected_note: str | None = None

    @property
    def can_finish(self) -> bool:
        return bool(self.start_time)

    @property
    def has_recorded_break(self) -> bool:
        return self.break_hours > 0


class AutoRecordViewModel:
    def __init__(
        self,
        *,
        clock: Clock | None = None,
        default_break_hours: float = 1.0,
        settings: SettingsRepository | None = None,
        user_id: int = 0,
        notes: DailyNoteRepository | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._settings = settings
        self._user_id = user_id
        self._notes = notes
        self.last_error = None
        self._restore_failed = False
        self.set_default_break_hours(default_break_hours)
        self._state = AutoRecordState(
            day=None,
            start_time=None,
            end_time=None,
            break_hours=self._default_break_hours,
            note="",
            work_type=WorkType.NORMAL.value,
        )
        if settings is not None:
            try:
                raw = settings.get(user_id, AUTO_RECORD_STATE_SETTING_KEY)
                if raw:
                    if len(raw) > 1024 * 1024:
                        raise ValueError("auto_record_state_invalid")
                    data = json.loads(raw)
                    data["day"] = date.fromisoformat(data["day"])
                    for key in ("started_at", "break_started_at", "ended_at"):
                        data[key] = datetime.fromisoformat(data[key]) if data.get(key) else None
                    restored = AutoRecordState(**data)
                    if restored.started_at and restored.started_at.strftime("%H:%M") != restored.start_time:
                        local_start = restored.started_at.astimezone()
                        if local_start.strftime("%H:%M") == restored.start_time and local_start.date() == restored.day:
                            restored = replace(restored, started_at=local_start)
                    if (not isinstance(restored.active, bool) or not isinstance(restored.pending_save, bool)
                            or not isinstance(restored.break_active, bool) or not math.isfinite(restored.break_hours)
                            or restored.break_hours < 0 or restored.break_hours > 24
                            or not isinstance(restored.note, str) or (restored.active and restored.pending_save)
                            or not (restored.active or restored.pending_save)
                            or (restored.expected_note is not None and not isinstance(restored.expected_note, str))
                            or parse_time(restored.start_time) != restored.start_time
                            or not restored.start_time or normalize_work_type(restored.work_type).value != restored.work_type
                            or (restored.active and (restored.started_at is None or restored.end_time))
                            or (restored.pending_save and not parse_time(restored.end_time))
                            or (restored.break_active and (not restored.active or restored.break_started_at is None))
                            or any(value is not None and value.tzinfo is None for value in (restored.started_at, restored.break_started_at, restored.ended_at))):
                        raise ValueError("auto_record_state_invalid")
                    if restored.pending_save:
                        normalize_work_log(WorkLog(
                            user_id, restored.day, restored.start_time, restored.end_time,
                            restored.break_hours, restored.note, normalize_work_type(restored.work_type),
                            started_at=restored.started_at if restored.ended_at else None,
                            ended_at=restored.ended_at,
                        ))
                    self._state = restored
            except Exception:
                self._restore_failed = True
                self.last_error = InfrastructureError("auto_record_restore_failed", "auto_record_restore_failed")

    def _set_state(self, state: AutoRecordState) -> Result[AutoRecordState]:
        if self._restore_failed:
            return Result.failure(self.last_error)
        if not math.isfinite(state.break_hours) or not 0 <= state.break_hours <= 24:
            return Result.failure(ValidationError("break_hours_too_long", "break_hours_too_long"))
        if self._settings is not None:
            try:
                if state.active or state.pending_save:
                    data = asdict(state)
                    data["day"] = state.day.isoformat()
                    for key in ("started_at", "break_started_at", "ended_at"):
                        data[key] = data[key].isoformat() if data[key] else None
                    encoded = json.dumps(data, allow_nan=False)
                    if len(encoded) > 1024 * 1024:
                        raise ValueError("auto_record_state_invalid")
                    self._settings.set(self._user_id, AUTO_RECORD_STATE_SETTING_KEY, encoded)
                else:
                    self._settings.delete(self._user_id, AUTO_RECORD_STATE_SETTING_KEY)
            except Exception:
                self.last_error = InfrastructureError("auto_record_state_save_failed", "auto_record_state_save_failed")
                return Result.failure(self.last_error)
        self.last_error = None
        self._state = state
        return Result.success(state)

    def reset_saved_state(self) -> Result[AutoRecordState]:
        failed = self._restore_failed
        self._restore_failed = False
        result = self._set_state(AutoRecordState(None, None, None, self._default_break_hours, "", WorkType.NORMAL.value))
        if not result.ok:
            self._restore_failed = failed
        return result

    def acknowledge_saved(self, day: date, start_time: str | None, end_time: str | None) -> Result[AutoRecordState]:
        if (self._state.active or self._state.pending_save) and day == self._state.day and start_time and end_time:
            return self._set_state(replace(self._state, start_time=start_time, end_time=end_time, active=False,
                                           break_active=False, break_started_at=None, pending_save=False))
        return Result.success(self._state)

    def state(self, now: datetime | None = None) -> AutoRecordState:
        return replace(
            self._state,
            break_hours=self._current_break_hours(self._coerce_now(now)),
        )

    def load_existing(
        self,
        *,
        day: date,
        start_time: str | None,
        end_time: str | None,
        break_hours: float,
        note: str,
        work_type: str,
    ) -> Result[AutoRecordState]:
        if self._state.active or self._state.pending_save:
            return Result.success(self._state)
        try:
            normalized_work_type = normalize_work_type(work_type).value
            normalized_start = parse_time(start_time)
            normalized_end = parse_time(end_time)
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        self._state = AutoRecordState(
            day=day,
            start_time=normalized_start,
            end_time=normalized_end,
            break_hours=max(float(break_hours or 0), 0.0),
            note=str(note or ""),
            work_type=normalized_work_type,
            active=bool(normalized_start and not normalized_end),
        )
        return Result.success(self._state)

    def set_default_break_hours(self, hours: float) -> None:
        value = float(hours)
        if not math.isfinite(value) or not 0 <= value <= 4:
            raise ValueError("break_hours_too_long")
        self._default_break_hours = value

    def start(
        self,
        now: datetime | None = None,
        *,
        note: str | None = None,
        work_type: str | None = None,
    ) -> Result[AutoRecordState]:
        moment = self._coerce_now(now)
        if self._state.pending_save:
            return Result.failure(ValidationError("auto_record_pending_save", "auto_record_pending_save"))
        if self._state.active and not self._state.end_time:
            return Result.failure(
                ValidationError("auto_record_already_active", "auto_record_already_active")
            )
        try:
            normalized_work_type = normalize_work_type(
                work_type or self._state.work_type or WorkType.NORMAL.value
            ).value
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        next_state = AutoRecordState(
            day=moment.date(),
            start_time=_time_text(moment),
            end_time=None,
            break_hours=self._default_break_hours,
            note=self._state.note if note is None else str(note),
            work_type=normalized_work_type,
            active=True,
            started_at=moment,
        )
        if self._notes is not None:
            try:
                next_state = replace(next_state, expected_note=self._notes.get_for_day(self._user_id, moment.date()).content)
            except Exception:
                return Result.failure(InfrastructureError("note_load_failed", "note_load_failed"))
        return self._set_state(next_state)

    def finish(self, now: datetime | None = None) -> Result[AutoRecordEntryDraft]:
        moment = self._coerce_now(now)
        if not self._state.start_time or self._state.day is None:
            return Result.failure(
                ValidationError("auto_record_not_started", "auto_record_not_started")
            )
        start = self._state.started_at or datetime.combine(self._state.day, datetime.strptime(self._state.start_time, "%H:%M").time()).astimezone()
        elapsed = _elapsed_seconds(moment, start)
        if elapsed <= 0 or elapsed > MAX_SHIFT_HOURS * 3600:
            return Result.failure(ValidationError("time_range_invalid", "time_range_invalid"))
        break_hours = _round_quarter_hours(self._current_break_hours(moment)) if self._state.break_active else self._state.break_hours
        try:
            normalize_work_log(WorkLog(user_id=0, day=self._state.day, start_time=self._state.start_time,
                                      end_time=_time_text(moment), break_hours=break_hours,
                                      note=self._state.note, work_type=self._state.work_type,
                                      started_at=start.replace(second=0, microsecond=0), ended_at=moment.replace(second=0, microsecond=0)))
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        updated = replace(
            self._state,
            break_hours=break_hours,
            end_time=_time_text(moment),
            active=False,
            break_active=False,
            break_started_at=None,
            pending_save=True,
            ended_at=moment,
        )
        saved = self._set_state(updated)
        if not saved.ok:
            return Result.failure(saved.error)
        return self.draft()

    def draft(self, now: datetime | None = None) -> Result[AutoRecordEntryDraft]:
        state = self.state(now)
        if state.day is None or not state.start_time:
            return Result.failure(
                ValidationError("auto_record_not_started", "auto_record_not_started")
            )
        return Result.success(
            AutoRecordEntryDraft(
                day=state.day,
                start_time=state.start_time,
                end_time=state.end_time,
                break_hours=state.break_hours,
                note=state.note,
                work_type=state.work_type,
            )
        )

    def restart_break(self, now: datetime | None = None) -> Result[AutoRecordState]:
        return self._start_break(self._coerce_now(now), resume=False)

    def continue_break(self, now: datetime | None = None) -> Result[AutoRecordState]:
        return self._start_break(self._coerce_now(now), resume=True)

    def end_break(self, now: datetime | None = None) -> Result[AutoRecordState]:
        moment = self._coerce_now(now)
        if not self._state.break_active or self._state.break_started_at is None:
            return Result.failure(
                ValidationError("auto_record_break_not_active", "auto_record_break_not_active")
            )
        updated = replace(
            self._state,
            break_hours=_round_quarter_hours(
                _elapsed_seconds(moment, self._state.break_started_at) / 3600
            ),
            break_active=False,
            break_started_at=None,
        )
        return self._set_state(updated)

    def add_quick_break(self, minutes: int) -> Result[AutoRecordState]:
        try:
            numeric_minutes = int(minutes)
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        if numeric_minutes <= 0:
            return Result.failure(
                ValidationError("auto_record_break_minutes_invalid", "auto_record_break_minutes_invalid")
            )
        updated = replace(
            self._state,
            break_hours=_round_quarter_hours(
                self._current_break_hours(self._coerce_now(None)) + numeric_minutes / 60
            ),
            break_active=False,
            break_started_at=None,
        )
        return self._set_state(updated)

    def update_details(self, *, note: str, work_type: str) -> Result[AutoRecordState]:
        try:
            normalized = normalize_work_type(work_type).value
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        updated = replace(self._state, note=str(note or ""), work_type=normalized)
        if updated == self._state:
            return Result.success(self._state)
        return self._set_state(updated)

    def _start_break(self, now: datetime, *, resume: bool) -> Result[AutoRecordState]:
        if self._state.break_active:
            return Result.failure(
                ValidationError("auto_record_break_already_active", "auto_record_break_already_active")
            )
        offset = self._state.break_hours if resume else 0.0
        updated = replace(
            self._state,
            break_hours=max(float(offset or 0), 0.0),
            break_active=True,
            break_started_at=now.astimezone(timezone.utc) - timedelta(hours=max(float(offset or 0), 0.0)),
        )
        saved = self._set_state(updated)
        if not saved.ok:
            return saved
        return Result.success(self.state(now))

    def _current_break_hours(self, now: datetime) -> float:
        if not self._state.break_active or self._state.break_started_at is None:
            return self._state.break_hours
        elapsed = _elapsed_seconds(now, self._state.break_started_at) / 3600
        return max(elapsed, 0.0)

    def _coerce_now(self, now: datetime | None) -> datetime:
        value = now if now is not None else self._clock()
        return value.astimezone() if value.tzinfo is None else value


def _time_text(moment: datetime) -> str:
    return moment.strftime("%H:%M")


def _elapsed_seconds(end: datetime, start: datetime) -> float:
    return (end.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds()


def _round_quarter_hours(hours: float) -> float:
    return math.floor(max(float(hours or 0), 0.0) * 4 + 0.5) / 4
