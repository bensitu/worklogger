"""Auto-record presentation state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta

from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkType
from worklogger.domain.worklog.rules import normalize_work_type, parse_time


Clock = Callable[[], datetime]


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
    ) -> None:
        self._clock = clock or datetime.now
        self._default_break_hours = max(float(default_break_hours or 0), 0.0)
        self._state = AutoRecordState(
            day=None,
            start_time=None,
            end_time=None,
            break_hours=self._default_break_hours,
            note="",
            work_type=WorkType.NORMAL.value,
        )

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

    def start(
        self,
        now: datetime | None = None,
        *,
        note: str | None = None,
        work_type: str | None = None,
    ) -> Result[AutoRecordState]:
        moment = self._coerce_now(now)
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
        self._state = AutoRecordState(
            day=moment.date(),
            start_time=_time_text(moment),
            end_time=None,
            break_hours=self._default_break_hours,
            note=self._state.note if note is None else str(note),
            work_type=normalized_work_type,
            active=True,
        )
        return Result.success(self._state)

    def finish(self, now: datetime | None = None) -> Result[AutoRecordEntryDraft]:
        moment = self._coerce_now(now)
        if not self._state.start_time or self._state.day is None:
            return Result.failure(
                ValidationError("auto_record_not_started", "auto_record_not_started")
            )
        if self._state.break_active:
            ended = self.end_break(moment)
            if not ended.ok:
                return Result.failure(ended.error)
        self._state = replace(
            self._state,
            end_time=_time_text(moment),
            active=False,
            break_active=False,
            break_started_at=None,
        )
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
        self._state = replace(
            self._state,
            break_hours=_round_quarter_hours(
                (moment - self._state.break_started_at).total_seconds() / 3600
            ),
            break_active=False,
            break_started_at=None,
        )
        return Result.success(self._state)

    def add_quick_break(self, minutes: int) -> Result[AutoRecordState]:
        try:
            numeric_minutes = int(minutes)
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        if numeric_minutes <= 0:
            return Result.failure(
                ValidationError("auto_record_break_minutes_invalid", "auto_record_break_minutes_invalid")
            )
        self._state = replace(
            self._state,
            break_hours=_round_quarter_hours(
                self._current_break_hours(self._coerce_now(None)) + numeric_minutes / 60
            ),
            break_active=False,
            break_started_at=None,
        )
        return Result.success(self._state)

    def set_note(self, note: str) -> AutoRecordState:
        self._state = replace(self._state, note=str(note or ""))
        return self._state

    def set_work_type(self, work_type: str) -> Result[AutoRecordState]:
        try:
            normalized = normalize_work_type(work_type).value
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        self._state = replace(self._state, work_type=normalized)
        return Result.success(self._state)

    def _start_break(self, now: datetime, *, resume: bool) -> Result[AutoRecordState]:
        if self._state.break_active:
            return Result.failure(
                ValidationError("auto_record_break_already_active", "auto_record_break_already_active")
            )
        offset = self._state.break_hours if resume else 0.0
        self._state = replace(
            self._state,
            break_hours=max(float(offset or 0), 0.0),
            break_active=True,
            break_started_at=now - timedelta(hours=max(float(offset or 0), 0.0)),
        )
        return Result.success(self.state(now))

    def _current_break_hours(self, now: datetime) -> float:
        if not self._state.break_active or self._state.break_started_at is None:
            return self._state.break_hours
        elapsed = (now - self._state.break_started_at).total_seconds() / 3600
        return max(elapsed, 0.0)

    def _coerce_now(self, now: datetime | None) -> datetime:
        return now if now is not None else self._clock()


def _time_text(moment: datetime) -> str:
    return moment.strftime("%H:%M")


def _round_quarter_hours(hours: float) -> float:
    return round(max(float(hours or 0), 0.0) * 4) / 4
