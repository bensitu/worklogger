from __future__ import annotations

from datetime import date
import unittest

from worklogger.app.commands.work_log_commands import SaveWorkLogCommand
from worklogger.app.queries.calendar_queries import GetCalendarEventsForRangeQuery
from worklogger.app.queries.work_log_queries import GetMonthRecordsQuery, GetWorkLogQuery
from worklogger.app.use_cases.calendar import GetCalendarEventsForRangeHandler
from worklogger.app.use_cases.work_logs import (
    GetMonthRecordsHandler,
    GetWorkLogHandler,
    SaveWorkLogHandler,
)
from worklogger.domain.calendar.models import CalendarEvent
from worklogger.domain.calendar.repositories import CalendarEventRepository
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkLog, WorkType
from worklogger.presentation.theme import ThemeEngine, normalize_hex_color
from worklogger.presentation.viewmodels import (
    CalendarDisplayOptions,
    CalendarViewModel,
    StatsPanelViewModel,
    WorkLogEntryViewModel,
)


class MemoryWorkLogRepository:
    def __init__(self) -> None:
        self.records: dict[tuple[int, date], WorkLog] = {}

    def get_for_day(self, user_id: int, day: date) -> WorkLog | None:
        return self.records.get((user_id, day))

    def list_for_month(self, user_id: int, year: int, month: int) -> tuple[WorkLog, ...]:
        return tuple(
            record
            for (record_user_id, record_day), record in sorted(self.records.items())
            if record_user_id == user_id
            and record_day.year == year
            and record_day.month == month
        )

    def list_all(self, user_id: int) -> tuple[WorkLog, ...]:
        return tuple(
            record
            for (record_user_id, _day), record in sorted(self.records.items())
            if record_user_id == user_id
        )

    def save(self, work_log: WorkLog) -> None:
        self.records[(work_log.user_id, work_log.day)] = work_log

    def remove(self, user_id: int, day: date) -> None:
        self.records.pop((user_id, day), None)


class MemoryCalendarRepository(CalendarEventRepository):
    def __init__(self, events: tuple[CalendarEvent, ...] = ()) -> None:
        self.events = events

    def list_for_day(self, user_id: int, day: date) -> tuple[CalendarEvent, ...]:
        return tuple(
            event
            for event in self.events
            if event.user_id == user_id and event.day == day
        )

    def list_for_range(
        self,
        user_id: int,
        start_day: date,
        end_day: date,
    ) -> tuple[CalendarEvent, ...]:
        return tuple(
            event
            for event in self.events
            if event.user_id == user_id and start_day <= event.day <= end_day
        )

    def replace_all(self, user_id: int, events: tuple[CalendarEvent, ...]) -> int:
        self.events = tuple(event for event in events if event.user_id == user_id)
        return len(self.events)

    def clear(self, user_id: int) -> None:
        self.events = tuple(event for event in self.events if event.user_id != user_id)


class FailingMonthRecordsHandler:
    def handle(self, query: GetMonthRecordsQuery) -> Result[tuple[WorkLog, ...]]:
        return Result.failure(ValidationError("month_failed", "month_failed"))


class PresentationViewModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.work_logs = MemoryWorkLogRepository()
        self.month_handler = GetMonthRecordsHandler(self.work_logs)
        self.get_handler = GetWorkLogHandler(self.work_logs)
        self.save_handler = SaveWorkLogHandler(self.work_logs)

    def save_work_log(
        self,
        day: date,
        *,
        start_time: str | None,
        end_time: str | None,
        break_hours: float,
        note: str,
        work_type: WorkType,
    ) -> WorkLog:
        result = self.save_handler.handle(
            SaveWorkLogCommand(
                user_id=1,
                day=day,
                start_time=start_time,
                end_time=end_time,
                break_hours=break_hours,
                note=note,
                work_type=work_type.value,
            )
        )
        self.assertTrue(result.ok, result.error)
        assert result.value is not None
        return result.value

    def test_calendar_viewmodel_builds_month_cells_and_markers(self) -> None:
        self.save_work_log(
            date(2026, 4, 20),
            start_time="22:00",
            end_time="09:00",
            break_hours=1.0,
            note="Night shift",
            work_type=WorkType.NORMAL,
        )
        self.save_work_log(
            date(2026, 4, 21),
            start_time=None,
            end_time=None,
            break_hours=0.0,
            note="Leave",
            work_type=WorkType.PAID_LEAVE,
        )
        self.work_logs.save(
            WorkLog(
                user_id=1,
                day=date(2026, 4, 22),
                note="Standalone note",
                work_type=WorkType.NORMAL,
            )
        )
        events = GetCalendarEventsForRangeHandler(
            MemoryCalendarRepository(
                (
                    CalendarEvent(
                        id=1,
                        user_id=1,
                        day=date(2026, 4, 20),
                        summary="Planning",
                    ),
                )
            )
        )
        view_model = CalendarViewModel(
            user_id=1,
            month_records_handler=self.month_handler,
            calendar_events_handler=events,
        )

        result = view_model.build_month(
            year=2026,
            month=4,
            selected_day=date(2026, 4, 20),
            today=date(2026, 4, 13),
            holidays={date(2026, 4, 29): "Holiday"},
            options=CalendarDisplayOptions(standard_work_hours=8.0),
        )

        self.assertTrue(result.ok, result.error)
        assert result.value is not None
        state = result.value
        self.assertEqual(state.week_headers, ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"))
        self.assertEqual(len(state.cells), 42)
        self.assertEqual(state.cells[0].day, date(2026, 3, 29))

        selected = next(cell for cell in state.cells if cell.day == date(2026, 4, 20))
        self.assertTrue(selected.is_selected)
        self.assertEqual(selected.style.key, "selected")
        self.assertEqual(selected.text_lines, ("20", "10.0h", "+2.0h"))
        self.assertTrue(selected.show_overnight_marker)
        self.assertEqual(selected.event_count, 1)
        self.assertEqual(selected.work_type_marker_color, None)

        leave = next(cell for cell in state.cells if cell.day == date(2026, 4, 21))
        self.assertTrue(leave.is_leave)
        self.assertEqual(leave.leave_hours, 8.0)
        self.assertEqual(leave.work_type_marker_color, "#2a9a2a")

        note = next(cell for cell in state.cells if cell.day == date(2026, 4, 22))
        self.assertTrue(note.has_note_marker)
        self.assertEqual(note.note_tooltip, "Standalone note")

        holiday = next(cell for cell in state.cells if cell.day == date(2026, 4, 29))
        self.assertTrue(holiday.is_holiday)
        self.assertIn("Holiday", holiday.text_lines)
        self.assertIn(10.0, state.weekly_totals)

    def test_calendar_viewmodel_supports_monday_start_and_load_errors(self) -> None:
        view_model = CalendarViewModel(
            user_id=1,
            month_records_handler=self.month_handler,
        )

        monday = view_model.build_month(
            year=2026,
            month=4,
            selected_day=date(2026, 4, 1),
            today=date(2026, 4, 1),
            options=CalendarDisplayOptions(week_start_monday=True),
        )

        self.assertTrue(monday.ok, monday.error)
        assert monday.value is not None
        self.assertEqual(monday.value.week_headers[0], "Mon")
        self.assertEqual(monday.value.cells[0].day, date(2026, 3, 30))

        failing = CalendarViewModel(
            user_id=1,
            month_records_handler=FailingMonthRecordsHandler(),
        )
        failed = failing.build_month(
            year=2026,
            month=4,
            selected_day=date(2026, 4, 1),
        )
        self.assertFalse(failed.ok)
        self.assertEqual(failed.error.code if failed.error else "", "month_failed")

    def test_worklog_entry_viewmodel_tracks_dirty_preview_and_save(self) -> None:
        view_model = WorkLogEntryViewModel(
            user_id=1,
            get_handler=self.get_handler,
            save_handler=self.save_handler,
            default_break_hours=1.0,
        )

        empty = view_model.load(date(2026, 4, 29), holiday_note="Holiday")

        self.assertTrue(empty.ok, empty.error)
        assert empty.value is not None
        self.assertEqual(empty.value.note, "Holiday")
        self.assertFalse(empty.value.dirty)

        preview = view_model.preview(
            date(2026, 4, 29),
            start_time="2200",
            end_time="0900",
            break_hours=1.0,
            note="Holiday",
            work_type=WorkType.NORMAL.value,
        )

        self.assertTrue(preview.ok, preview.error)
        assert preview.value is not None
        self.assertTrue(preview.value.dirty)
        self.assertTrue(preview.value.can_save)
        self.assertEqual(preview.value.start_time, "22:00")
        self.assertEqual(preview.value.end_time, "09:00")
        self.assertTrue(preview.value.is_overnight)
        self.assertEqual(preview.value.worked_hours, 10.0)

        saved = view_model.save(preview.value)

        self.assertTrue(saved.ok, saved.error)
        assert saved.value is not None
        self.assertFalse(saved.value.dirty)
        stored = self.work_logs.get_for_day(1, date(2026, 4, 29))
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.start_time, "22:00")
        self.assertEqual(stored.end_time, "09:00")
        self.assertTrue(stored.overnight)

        invalid = view_model.preview(
            date(2026, 4, 29),
            start_time="09:00",
            end_time=None,
            break_hours=1.0,
            note="",
            work_type=WorkType.NORMAL.value,
        )
        self.assertTrue(invalid.ok)
        assert invalid.value is not None
        self.assertFalse(invalid.value.can_save)
        self.assertEqual(invalid.value.errors, ("time_range_incomplete",))

    def test_stats_panel_viewmodel_builds_month_summary(self) -> None:
        self.save_work_log(
            date(2026, 4, 20),
            start_time="09:00",
            end_time="18:00",
            break_hours=1.0,
            note="",
            work_type=WorkType.NORMAL,
        )
        self.save_work_log(
            date(2026, 4, 21),
            start_time="09:00",
            end_time="20:00",
            break_hours=1.0,
            note="",
            work_type=WorkType.REMOTE,
        )
        self.save_work_log(
            date(2026, 4, 22),
            start_time=None,
            end_time=None,
            break_hours=0.0,
            note="Leave",
            work_type=WorkType.PAID_LEAVE,
        )
        view_model = StatsPanelViewModel(
            user_id=1,
            month_records_handler=self.month_handler,
        )

        result = view_model.build_month(
            year=2026,
            month=4,
            standard_work_hours=8.0,
            monthly_target_hours=40.0,
        )

        self.assertTrue(result.ok, result.error)
        assert result.value is not None
        self.assertEqual(result.value.total_hours, 18.0)
        self.assertEqual(result.value.overtime_hours, 2.0)
        self.assertEqual(result.value.work_days, 2)
        self.assertEqual(result.value.leave_days, 1)
        self.assertEqual(result.value.average_hours, 9.0)
        self.assertEqual(result.value.target_progress, 0.45)

    def test_theme_engine_preserves_palette_and_calendar_priority(self) -> None:
        engine = ThemeEngine()

        self.assertEqual(normalize_hex_color("ABCDEF"), "#abcdef")
        self.assertEqual(normalize_hex_color("invalid"), "#4f8ef7")
        palette = engine.palette("custom", custom_color="#123456")
        self.assertEqual(palette.accent, "#123456")
        self.assertIn("#123456", engine.application_stylesheet("custom", custom_color="#123456"))

        style = engine.calendar_cell_style({"weekend", "holiday", "selected"})
        self.assertEqual(style.key, "selected")
        self.assertEqual(style.background, "#4f8ef7")
        self.assertEqual(
            engine.work_type_marker_color(WorkType.BUSINESS_TRIP),
            "#e07800",
        )


if __name__ == "__main__":
    unittest.main()
