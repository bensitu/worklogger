"""Calendar presentation ViewModel."""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

from worklogger.app.queries.calendar_queries import (
    GetCalendarEventsForRangeQuery,
    GetHolidaysForRangeQuery,
)
from worklogger.app.queries.work_log_queries import GetMonthRecordsQuery
from worklogger.domain.calendar.models import CalendarEvent, Holiday
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkLog, WorkType
from worklogger.infrastructure.i18n import _, ngettext
from worklogger.presentation.theme import CalendarCellStyle, ThemeEngine


class MonthRecordsHandler(Protocol):
    def handle(self, query: GetMonthRecordsQuery) -> Result[tuple[WorkLog, ...]]:
        ...


class CalendarEventsForRangeHandler(Protocol):
    def handle(
        self,
        query: GetCalendarEventsForRangeQuery,
    ) -> Result[tuple[CalendarEvent, ...]]:
        ...


class HolidaysForRangeHandler(Protocol):
    def handle(
        self,
        query: GetHolidaysForRangeQuery,
    ) -> Result[tuple[Holiday, ...]]:
        ...


@dataclass(frozen=True)
class CalendarDisplayOptions:
    show_holidays: bool = True
    show_note_markers: bool = True
    show_overnight_indicator: bool = True
    week_start_monday: bool = False
    standard_work_hours: float = 8.0


@dataclass(frozen=True)
class CalendarDayCell:
    day: date
    in_month: bool
    text_lines: tuple[str, ...]
    style: CalendarCellStyle
    is_today: bool
    is_selected: bool
    is_weekend: bool
    is_holiday: bool
    holiday_name: str
    work_type: str
    is_leave: bool
    worked_hours: float
    overtime_hours: float
    leave_hours: float
    weekly_total_hours: float
    has_note_marker: bool
    note_tooltip: str
    work_type_marker_color: str | None
    show_overnight_marker: bool
    event_count: int


@dataclass(frozen=True)
class CalendarMonthViewState:
    year: int
    month: int
    week_headers: tuple[str, ...]
    cells: tuple[CalendarDayCell, ...]
    weekly_totals: tuple[float, ...]


class CalendarViewModel:
    def __init__(
        self,
        *,
        user_id: int,
        month_records_handler: MonthRecordsHandler,
        calendar_events_handler: CalendarEventsForRangeHandler | None = None,
        holidays_handler: HolidaysForRangeHandler | None = None,
        holiday_country: str = "US",
        theme_engine: ThemeEngine | None = None,
    ) -> None:
        self._user_id = user_id
        self._month_records_handler = month_records_handler
        self._calendar_events_handler = calendar_events_handler
        self._holidays_handler = holidays_handler
        self._holiday_country = str(holiday_country or "US").strip().upper() or "US"
        self._theme_engine = theme_engine or ThemeEngine()

    def build_month(
        self,
        *,
        year: int,
        month: int,
        selected_day: date,
        today: date | None = None,
        holidays: Mapping[date, str] | None = None,
        options: CalendarDisplayOptions | None = None,
        theme: str = "blue",
        dark: bool = False,
        custom_color: str | None = None,
    ) -> Result[CalendarMonthViewState]:
        try:
            options = options or CalendarDisplayOptions()
            first_day = date(int(year), int(month), 1)
            monthrange(first_day.year, first_day.month)
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))

        grid_start = _month_grid_start(
            first_day,
            week_start_monday=options.week_start_monday,
        )
        grid_end = grid_start + timedelta(days=41)
        record_result = self._month_records_handler.handle(
            GetMonthRecordsQuery(
                user_id=self._user_id,
                year=first_day.year,
                month=first_day.month,
            )
        )
        if not record_result.ok:
            return Result.failure(
                record_result.error
                or ValidationError("calendar_load_failed", "calendar_load_failed")
            )

        event_result = self._events_for_range(grid_start, grid_end)
        if not event_result.ok:
            return Result.failure(
                event_result.error
                or ValidationError("calendar_load_failed", "calendar_load_failed")
            )

        records = {record.day: record for record in record_result.value or ()}
        events_by_day: dict[date, list[CalendarEvent]] = {}
        for event in event_result.value or ():
            events_by_day.setdefault(event.day, []).append(event)
        holidays_result = self._holiday_map(
            grid_start,
            grid_end,
            provided=holidays,
            enabled=options.show_holidays,
        )
        if not holidays_result.ok or holidays_result.value is None:
            return Result.failure(
                holidays_result.error
                or ValidationError("calendar_load_failed", "calendar_load_failed")
            )
        holiday_map = holidays_result.value
        today_value = today or date.today()

        weekly_totals = [0.0 for _week in range(6)]
        for offset in range(42):
            cell_day = grid_start + timedelta(days=offset)
            week_index = offset // 7
            record = records.get(cell_day)
            if record and not record.is_leave:
                weekly_totals[week_index] += record.worked_hours()

        cells: list[CalendarDayCell] = []
        for offset in range(42):
            cell_day = grid_start + timedelta(days=offset)
            week_index = offset // 7
            record = records.get(cell_day)
            cells.append(
                self._build_cell(
                    cell_day,
                    month=first_day.month,
                    selected_day=selected_day,
                    today=today_value,
                    record=record,
                    holiday_name=str(holiday_map.get(cell_day, "")).strip(),
                    events=tuple(events_by_day.get(cell_day, ())),
                    options=options,
                    weekly_total_hours=weekly_totals[week_index],
                    theme=theme,
                    dark=dark,
                    custom_color=custom_color,
                )
            )

        return Result.success(
            CalendarMonthViewState(
                year=first_day.year,
                month=first_day.month,
                week_headers=_week_headers(options.week_start_monday),
                cells=tuple(cells),
                weekly_totals=tuple(weekly_totals),
            )
        )

    def shift_day(self, day: date, days: int) -> date:
        try:
            return day + timedelta(days=int(days))
        except (OverflowError, TypeError, ValueError):
            return day

    def _events_for_range(
        self,
        start_day: date,
        end_day: date,
    ) -> Result[tuple[CalendarEvent, ...]]:
        if self._calendar_events_handler is None:
            return Result.success(())
        return self._calendar_events_handler.handle(
            GetCalendarEventsForRangeQuery(
                user_id=self._user_id,
                start_day=start_day,
                end_day=end_day,
            )
        )

    def _holiday_map(
        self,
        start_day: date,
        end_day: date,
        *,
        provided: Mapping[date, str] | None,
        enabled: bool,
    ) -> Result[dict[date, str]]:
        if not enabled:
            return Result.success({})
        if provided is not None:
            return Result.success(dict(provided))
        if self._holidays_handler is None:
            return Result.success({})
        result = self._holidays_handler.handle(
            GetHolidaysForRangeQuery(
                country=self._holiday_country,
                start_day=start_day,
                end_day=end_day,
            )
        )
        if not result.ok or result.value is None:
            return Result.failure(
                result.error
                or ValidationError("holiday_load_failed", "holiday_load_failed")
            )
        return Result.success({holiday.day: holiday.name for holiday in result.value})

    def _build_cell(
        self,
        cell_day: date,
        *,
        month: int,
        selected_day: date,
        today: date,
        record: WorkLog | None,
        holiday_name: str,
        events: tuple[CalendarEvent, ...],
        options: CalendarDisplayOptions,
        weekly_total_hours: float,
        theme: str,
        dark: bool,
        custom_color: str | None,
    ) -> CalendarDayCell:
        flags: set[str] = set()
        if cell_day == today:
            flags.add("today")
        if cell_day == selected_day:
            flags.add("selected")
        if cell_day.weekday() >= 5:
            flags.add("weekend")
        if holiday_name:
            flags.add("holiday")

        work_type = record.work_type.value if record else WorkType.NORMAL.value
        worked_hours = record.worked_hours() if record else 0.0
        overtime_hours = (
            max(worked_hours - float(options.standard_work_hours), 0.0)
            if record and not record.is_leave
            else 0.0
        )
        leave_hours = record.leave_hours() if record else 0.0
        note_text = (record.note if record else "").strip()
        has_note_marker = (
            bool(options.show_note_markers)
            and bool(note_text)
            and bool(record)
            and not record.has_times
            and note_text != holiday_name
        )
        text_lines = _cell_text_lines(cell_day, holiday_name, worked_hours, overtime_hours)
        return CalendarDayCell(
            day=cell_day,
            in_month=cell_day.month == month,
            text_lines=text_lines,
            style=self._theme_engine.calendar_cell_style(
                flags,
                theme=theme,
                dark=dark,
                custom_color=custom_color,
            ),
            is_today=cell_day == today,
            is_selected=cell_day == selected_day,
            is_weekend=cell_day.weekday() >= 5,
            is_holiday=bool(holiday_name),
            holiday_name=holiday_name,
            work_type=work_type,
            is_leave=bool(record and record.is_leave),
            worked_hours=worked_hours,
            overtime_hours=overtime_hours,
            leave_hours=leave_hours,
            weekly_total_hours=weekly_total_hours,
            has_note_marker=has_note_marker,
            note_tooltip=note_text[:200] if has_note_marker else "",
            work_type_marker_color=self._theme_engine.work_type_marker_color(
                work_type,
                dark=dark,
            ),
            show_overnight_marker=bool(
                options.show_overnight_indicator and record and record.is_overnight
            ),
            event_count=len(events),
        )


def _month_grid_start(first_day: date, *, week_start_monday: bool) -> date:
    raw_first = first_day.weekday()
    leading_days = raw_first if week_start_monday else (raw_first + 1) % 7
    return first_day - timedelta(days=leading_days)


def _week_headers(week_start_monday: bool) -> tuple[str, ...]:
    monday_first = (_("Mon"), _("Tue"), _("Wed"), _("Thu"), _("Fri"), _("Sat"), _("Sun"))
    sunday_first = (_("Sun"), _("Mon"), _("Tue"), _("Wed"), _("Thu"), _("Fri"), _("Sat"))
    return monday_first if week_start_monday else sunday_first


def _cell_text_lines(
    cell_day: date,
    holiday_name: str,
    worked_hours: float,
    overtime_hours: float,
) -> tuple[str, ...]:
    lines = [str(cell_day.day)]
    if holiday_name:
        lines.append(holiday_name)
    if worked_hours > 0:
        lines.append(f"{worked_hours:.1f}{_('h')}")
    if overtime_hours > 0:
        lines.append(f"{_('+')}{overtime_hours:.1f}{_('h')}")
    return tuple(lines)


def event_count_label(count: int) -> str:
    return ngettext("{count} event", "{count} events", count).format(count=count)
