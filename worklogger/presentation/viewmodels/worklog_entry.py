"""Work log entry presentation ViewModel."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from worklogger.app.commands.work_log_commands import SaveWorkLogCommand
from worklogger.app.queries.work_log_queries import GetWorkLogQuery
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkLog, WorkType
from worklogger.domain.worklog.rules import (
    normalize_work_log,
    normalize_work_type,
    parse_time,
)


class WorkLogGetHandler(Protocol):
    def handle(self, query: GetWorkLogQuery) -> Result[WorkLog | None]:
        ...


class WorkLogSaveHandler(Protocol):
    def handle(self, command: SaveWorkLogCommand) -> Result[WorkLog]:
        ...


@dataclass(frozen=True)
class WorkLogEntryForm:
    user_id: int
    day: date
    start_time: str | None
    end_time: str | None
    break_hours: float
    note: str
    work_type: str
    worked_hours: float
    is_overnight: bool
    is_leave: bool
    dirty: bool
    errors: tuple[str, ...] = ()

    @property
    def can_save(self) -> bool:
        return not self.errors and self.dirty


class WorkLogEntryViewModel:
    def __init__(
        self,
        *,
        user_id: int,
        get_handler: WorkLogGetHandler,
        save_handler: WorkLogSaveHandler,
        default_break_hours: float = 1.0,
    ) -> None:
        self._user_id = user_id
        self._get_handler = get_handler
        self._save_handler = save_handler
        self._default_break_hours = float(default_break_hours)
        self._loaded: dict[date, WorkLog | None] = {}
        self._holiday_notes: dict[date, str] = {}

    def load(
        self,
        day: date,
        *,
        holiday_note: str = "",
    ) -> Result[WorkLogEntryForm]:
        loaded = self._get_handler.handle(GetWorkLogQuery(self._user_id, day))
        if not loaded.ok:
            return Result.failure(loaded.error or ValidationError("worklog_load_failed", "worklog_load_failed"))
        record = loaded.value
        self._loaded[day] = record
        self._holiday_notes[day] = str(holiday_note or "").strip()
        if record is None:
            return Result.success(
                self.preview(
                    day,
                    start_time=None,
                    end_time=None,
                    break_hours=self._default_break_hours,
                    note=self._holiday_notes[day],
                    work_type=WorkType.NORMAL.value,
                ).value
            )
        return self.preview(
            day,
            start_time=record.start_time,
            end_time=record.end_time,
            break_hours=record.break_hours,
            note=record.note,
            work_type=record.work_type.value,
        )

    def preview(
        self,
        day: date,
        *,
        start_time: str | None,
        end_time: str | None,
        break_hours: float,
        note: str,
        work_type: str,
    ) -> Result[WorkLogEntryForm]:
        errors: tuple[str, ...] = ()
        normalized: WorkLog | None = None
        try:
            normalized = normalize_work_log(
                WorkLog(
                    user_id=self._user_id,
                    day=day,
                    start_time=start_time,
                    end_time=end_time,
                    break_hours=break_hours,
                    note=note,
                    work_type=normalize_work_type(work_type),
                )
            )
        except (TypeError, ValueError) as exc:
            errors = (str(exc),)

        form = _form_from_values(
            user_id=self._user_id,
            day=day,
            start_time=normalized.start_time if normalized else parse_time(start_time),
            end_time=normalized.end_time if normalized else parse_time(end_time),
            break_hours=float(break_hours or 0),
            note=str(note or ""),
            work_type=(
                normalized.work_type.value
                if normalized
                else _safe_work_type_value(work_type)
            ),
            record=normalized,
            dirty=self._is_dirty(
                day,
                start_time=normalized.start_time if normalized else parse_time(start_time),
                end_time=normalized.end_time if normalized else parse_time(end_time),
                break_hours=float(break_hours or 0),
                note=str(note or ""),
                work_type=(
                    normalized.work_type.value
                    if normalized
                    else _safe_work_type_value(work_type)
                ),
            ),
            errors=errors,
        )
        return Result.success(form)

    def save(self, form: WorkLogEntryForm) -> Result[WorkLogEntryForm]:
        if form.errors:
            return Result.failure(ValidationError(form.errors[0], form.errors[0]))
        saved = self._save_handler.handle(
            SaveWorkLogCommand(
                user_id=form.user_id,
                day=form.day,
                start_time=form.start_time,
                end_time=form.end_time,
                break_hours=form.break_hours,
                note=form.note,
                work_type=form.work_type,
            )
        )
        if not saved.ok:
            return Result.failure(saved.error or ValidationError("worklog_save_failed", "worklog_save_failed"))
        self._loaded[form.day] = saved.value
        assert saved.value is not None
        return Result.success(
            _form_from_values(
                user_id=self._user_id,
                day=saved.value.day,
                start_time=saved.value.start_time,
                end_time=saved.value.end_time,
                break_hours=saved.value.break_hours,
                note=saved.value.note,
                work_type=saved.value.work_type.value,
                record=saved.value,
                dirty=False,
                errors=(),
            )
        )

    def _is_dirty(
        self,
        day: date,
        *,
        start_time: str | None,
        end_time: str | None,
        break_hours: float,
        note: str,
        work_type: str,
    ) -> bool:
        holiday_note = self._holiday_notes.get(day, "")
        current_note = _note_for_compare(note, holiday_note)
        record = self._loaded.get(day)
        if record is None:
            saved = (
                None,
                None,
                self._default_break_hours,
                "",
                WorkType.NORMAL.value,
            )
        else:
            saved = (
                record.start_time,
                record.end_time,
                record.break_hours,
                _note_for_compare(record.note, holiday_note),
                record.work_type.value,
            )
        current = (
            start_time,
            end_time,
            float(break_hours or 0),
            current_note,
            _safe_work_type_value(work_type),
        )
        return current != saved


def _form_from_values(
    *,
    user_id: int,
    day: date,
    start_time: str | None,
    end_time: str | None,
    break_hours: float,
    note: str,
    work_type: str,
    record: WorkLog | None,
    dirty: bool,
    errors: tuple[str, ...],
) -> WorkLogEntryForm:
    return WorkLogEntryForm(
        user_id=user_id,
        day=day,
        start_time=start_time,
        end_time=end_time,
        break_hours=float(break_hours or 0),
        note=note,
        work_type=work_type,
        worked_hours=record.worked_hours() if record else 0.0,
        is_overnight=bool(record and record.is_overnight),
        is_leave=bool(record and record.is_leave),
        dirty=dirty,
        errors=errors,
    )


def _note_for_compare(note: str, holiday_note: str) -> str:
    value = str(note or "")
    return "" if holiday_note and value.strip() == holiday_note else value


def _safe_work_type_value(work_type: str | WorkType) -> str:
    try:
        return normalize_work_type(work_type).value
    except (TypeError, ValueError):
        return WorkType.NORMAL.value
