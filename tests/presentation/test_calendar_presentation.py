from __future__ import annotations

from datetime import date
import unittest

from worklogger.app.queries.calendar_queries import GetHolidaysForRangeQuery
from worklogger.app.queries.work_log_queries import GetMonthRecordsQuery
from worklogger.domain.calendar.models import Holiday
from worklogger.domain.notes.models import DailyNote
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkLog
from worklogger.presentation.viewmodels import CalendarDisplayOptions, CalendarViewModel


class EmptyMonthRecordsHandler:
    def list_range(self, user_id, start, end):
        return Result.success(())

    def handle(self, query: GetMonthRecordsQuery) -> Result[tuple[WorkLog, ...]]:
        return Result.success(())


class RecordingHolidaysHandler:
    def __init__(self) -> None:
        self.queries: list[GetHolidaysForRangeQuery] = []

    def handle(
        self,
        query: GetHolidaysForRangeQuery,
    ) -> Result[tuple[Holiday, ...]]:
        self.queries.append(query)
        return Result.success(
            (
                Holiday(day=date(2026, 5, 4), name="Greenery Day"),
            )
        )


class CalendarPresentationTests(unittest.TestCase):
    def test_calendar_keeps_zero_hours_but_only_shows_positive_overtime(self):
        from worklogger.presentation.viewmodels.calendar import _cell_text_lines
        from worklogger.infrastructure.i18n import _

        day = date(2026, 10, 16)
        for holiday in ("", "Holiday"):
            for worked, overtime in ((0, 0), (8, 0), (9, 1)):
                lines = _cell_text_lines(day, holiday, worked, overtime)
                self.assertIn(f"{worked:.1f}{_('h')}", lines)
                self.assertEqual(any(line.startswith(_('+')) for line in lines), overtime > 0)

    def test_daily_note_markers_remain_visible_with_work_and_calendar_events(self):
        from types import SimpleNamespace

        from worklogger.domain.calendar.models import CalendarEvent

        day = date(2026, 5, 4)
        note = DailyNote(1, day, "Greenery Day")
        notes = SimpleNamespace(list_range=lambda *_args: Result.success((note,)))
        for record in (None, WorkLog(1, day, "09:00", "17:00", note="Work description"),
                       WorkLog(1, day, "22:00", "06:00", note="Night shift")):
            for events in ((), (CalendarEvent(1, 1, day, "Planning"),)):
                for enabled in (False, True):
                    with self.subTest(record=record, events=events, enabled=enabled):
                        records = SimpleNamespace(list_range=lambda *_args: Result.success((record,) if record else ()))
                        model = CalendarViewModel(user_id=1, month_records_handler=records, notes_handler=notes,
                            calendar_events_handler=SimpleNamespace(handle=lambda _query: Result.success(events)))
                        result = model.build_month(year=2026, month=5, selected_day=day,
                            holidays={day: note.content}, options=CalendarDisplayOptions(show_note_markers=enabled))
                        self.assertTrue(result.ok, result.error)
                        cell = next(cell for cell in result.value.cells if cell.day == day)
                        self.assertEqual(cell.has_note_marker, enabled)
                        self.assertEqual(cell.note_tooltip, note.content if enabled else "")
                        self.assertEqual(cell.event_count, len(events))
                        self.assertEqual(cell.show_overnight_marker, bool(record and record.is_overnight))

    def test_work_descriptions_and_empty_daily_notes_do_not_create_note_markers(self):
        from types import SimpleNamespace

        day = date(2026, 5, 4)
        records = SimpleNamespace(list_range=lambda *_args: Result.success((
            WorkLog(1, day, "09:00", "17:00", note="Work description"),)))
        for content in (None, "", "   "):
            with self.subTest(content=content):
                notes = SimpleNamespace(list_range=lambda *_args: Result.success(
                    () if content is None else (DailyNote(1, day, content),)))
                model = CalendarViewModel(user_id=1, month_records_handler=records, notes_handler=notes)
                result = model.build_month(year=2026, month=5, selected_day=day)
                self.assertTrue(result.ok, result.error)
                cell = next(cell for cell in result.value.cells if cell.day == day)
                self.assertFalse(cell.has_note_marker)
                self.assertEqual(cell.note_tooltip, "")

    def test_visible_grid_includes_adjacent_month_records_and_week_totals(self):
        from worklogger.app.use_cases.work_logs import GetMonthRecordsHandler
        from tests.app.test_application_use_cases import MemoryWorkLogRepository

        repository = MemoryWorkLogRepository()
        for day in (date(2026, 4, 30), date(2026, 5, 1), date(2026, 6, 1)):
            repository.save(WorkLog(1, day, "09:00", "17:00"))
            repository.save(WorkLog(2, day, "09:00", "19:00"))
        model = CalendarViewModel(user_id=1, month_records_handler=GetMonthRecordsHandler(repository))
        result = model.build_month(year=2026, month=5, selected_day=date(2026, 5, 1))
        self.assertTrue(result.ok, result.error)
        cells = {cell.day: cell for cell in result.value.cells}
        for day in (date(2026, 4, 30), date(2026, 6, 1)):
            self.assertFalse(cells[day].in_month)
            self.assertEqual(cells[day].worked_hours, 8)
        self.assertEqual(cells[date(2026, 4, 30)].weekly_total_hours, 16)

    def test_explicit_holiday_map_overrides_provider_even_when_empty(self) -> None:
        holidays = RecordingHolidaysHandler()
        model = CalendarViewModel(user_id=1, month_records_handler=EmptyMonthRecordsHandler(),
                                  holidays_handler=holidays, holiday_country="JP")
        for provided in ({}, {date(2026, 5, 1): "Custom holiday"}):
            result = model.build_month(year=2026, month=5, selected_day=date(2026, 5, 1),
                                       holidays=provided)
            self.assertTrue(result.ok, result.error)
            actual = {cell.day: cell.holiday_name for cell in result.value.cells if cell.is_holiday}
            self.assertEqual(actual, provided)
        self.assertEqual(holidays.queries, [])

    def test_calendar_viewmodel_loads_holidays_when_enabled(self) -> None:
        holidays = RecordingHolidaysHandler()
        view_model = CalendarViewModel(
            user_id=1,
            month_records_handler=EmptyMonthRecordsHandler(),
            holidays_handler=holidays,
            holiday_country="jp",
        )

        result = view_model.build_month(
            year=2026,
            month=5,
            selected_day=date(2026, 5, 1),
            today=date(2026, 5, 1),
            options=CalendarDisplayOptions(show_holidays=True),
        )

        self.assertTrue(result.ok, result.error)
        assert result.value is not None
        holiday = next(cell for cell in result.value.cells if cell.day == date(2026, 5, 4))
        self.assertTrue(holiday.is_holiday)
        self.assertEqual(holiday.holiday_name, "Greenery Day")
        self.assertEqual(len(holidays.queries), 1)
        self.assertEqual(holidays.queries[0].country, "JP")

    def test_calendar_viewmodel_skips_holiday_handler_when_disabled(self) -> None:
        holidays = RecordingHolidaysHandler()
        view_model = CalendarViewModel(
            user_id=1,
            month_records_handler=EmptyMonthRecordsHandler(),
            holidays_handler=holidays,
        )

        result = view_model.build_month(
            year=2026,
            month=5,
            selected_day=date(2026, 5, 1),
            today=date(2026, 5, 1),
            options=CalendarDisplayOptions(show_holidays=False),
        )

        self.assertTrue(result.ok, result.error)
        self.assertEqual(holidays.queries, [])


if __name__ == "__main__":
    unittest.main()
