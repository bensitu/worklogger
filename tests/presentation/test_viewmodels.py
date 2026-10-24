from __future__ import annotations

from datetime import date
import unittest

from PySide6.QtGui import QColor, QPalette

from worklogger.app.queries.work_log_queries import GetMonthRecordsQuery
from worklogger.app.use_cases.calendar import GetCalendarEventsForRangeHandler
from worklogger.app.use_cases.work_logs import GetMonthRecordsHandler
from worklogger.domain.calendar.models import CalendarEvent
from worklogger.domain.calendar.repositories import CalendarEventRepository
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkLog, EntryType, CustomEntryType
from worklogger.domain.worklog.rules import normalize_work_log
from worklogger.presentation.theme import ThemeEngine, normalize_hex_color
from worklogger.presentation.viewmodels import (
    CalendarDisplayOptions,
    CalendarViewModel,
    StatsPanelViewModel,
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

    def save(self, work_log: WorkLog, *, expected_note: str | None = None) -> None:
        self.records[(work_log.user_id, work_log.day)] = work_log

    def list_range(self, user_id: int, start: date, end: date) -> tuple[WorkLog, ...]:
        return tuple(record for record in self.list_all(user_id) if start <= record.day <= end)

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
    def list_range(self, user_id, start, end):
        return Result.failure(ValidationError("month_failed", "month_failed"))

    def handle(self, query: GetMonthRecordsQuery) -> Result[tuple[WorkLog, ...]]:
        return Result.failure(ValidationError("month_failed", "month_failed"))


class PresentationViewModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.work_logs = MemoryWorkLogRepository()
        self.month_handler = GetMonthRecordsHandler(self.work_logs)

    def save_work_log(
        self,
        day: date,
        *,
        start_time: str | None,
        end_time: str | None,
        break_hours: float,
        note: str,
        entry_type: EntryType,
    ) -> WorkLog:
        record = normalize_work_log(
            WorkLog(
                user_id=1,
                day=day,
                start_time=start_time,
                end_time=end_time,
                break_hours=break_hours,
                note=note,
                entry_type=entry_type,
            )
        )
        self.work_logs.save(record)
        return record

    def test_calendar_viewmodel_builds_month_cells_and_markers(self) -> None:
        self.save_work_log(
            date(2026, 4, 20),
            start_time="22:00",
            end_time="09:00",
            break_hours=1.0,
            note="Night shift",
            entry_type=EntryType.NORMAL,
        )
        self.save_work_log(
            date(2026, 4, 21),
            start_time=None,
            end_time=None,
            break_hours=0.0,
            note="Leave",
            entry_type=EntryType.PAID_LEAVE,
        )
        self.work_logs.save(
            WorkLog(
                user_id=1,
                day=date(2026, 4, 22),
                note="Standalone note",
                entry_type=EntryType.NORMAL,
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
        self.assertEqual([(segment.key, segment.duration) for segment in selected.segments], [("normal", 10.0)])
        self.assertEqual(selected.segments[0].color, ThemeEngine().entry_type_color(EntryType.NORMAL))

        leave = next(cell for cell in state.cells if cell.day == date(2026, 4, 21))
        self.assertTrue(leave.is_leave)
        self.assertEqual(leave.leave_hours, 8.0)
        self.assertEqual([(segment.key, segment.duration) for segment in leave.segments], [("paid_leave", 8.0)])
        self.assertEqual(leave.segments[0].color, ThemeEngine().entry_type_color(EntryType.PAID_LEAVE))

        note = next(cell for cell in state.cells if cell.day == date(2026, 4, 22))
        self.assertTrue(note.has_note_marker)
        self.assertEqual(note.note_tooltip, "Standalone note")
        self.assertEqual(note.segments, ())

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

    def test_stats_panel_viewmodel_builds_month_summary(self) -> None:
        self.save_work_log(
            date(2026, 4, 20),
            start_time="09:00",
            end_time="18:00",
            break_hours=1.0,
            note="",
            entry_type=EntryType.NORMAL,
        )
        self.save_work_log(
            date(2026, 4, 21),
            start_time="09:00",
            end_time="20:00",
            break_hours=1.0,
            note="",
            entry_type=EntryType.REMOTE,
        )
        self.save_work_log(
            date(2026, 4, 22),
            start_time=None,
            end_time=None,
            break_hours=0.0,
            note="Leave",
            entry_type=EntryType.PAID_LEAVE,
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
        qt_palette = engine.qt_palette("custom", custom_color="#123456")
        self.assertEqual(qt_palette.color(QPalette.ColorRole.Highlight).name(), "#123456")

        style = engine.calendar_cell_style({"weekend", "holiday", "selected"})
        self.assertEqual(style.key, "selected")
        self.assertEqual(style.background, "#4f8ef7")
        self.assertEqual(
            engine.entry_type_color(EntryType.BUSINESS_TRIP),
            "#7865b6",
        )
        for dark in (False, True):
            colors = []
            for entry_type in EntryType:
                color = engine.entry_type_color(entry_type, dark=dark)
                self.assertIsNotNone(color)
                self.assertTrue(QColor(color).isValid())
                colors.append(color)
            self.assertEqual(len(colors), len(set(colors)))

    def test_custom_classification_colors_follow_stable_identity_within_semantic_categories(self):
        from dataclasses import replace

        engine = ThemeEngine()
        definitions = tuple(CustomEntryType(f"custom:{index:032x}", "Research") for index in range(1, 17))
        for dark in (False, True):
            colors = []
            for definition in definitions:
                expected = engine.entry_type_color(definition, dark=dark)
                self.assertTrue(QColor(expected).isValid())
                self.assertEqual(engine.entry_type_color(definition.value, dark=dark), expected)
                self.assertEqual(ThemeEngine().entry_type_color(definition, dark=dark), expected)
                for category in ("work", "break", "leave"):
                    changed = replace(definition, label="Revised", category=category, revision=3, archived=True)
                    color = engine.entry_type_color(changed, dark=dark)
                    self.assertEqual(color, engine.entry_type_color(definition.value, dark=dark, category=category))
                    self.assertEqual(color, engine.entry_type_color(replace(changed, label="Renamed"), dark=dark))
                    if category != "work":
                        self.assertNotEqual(color, expected)
                colors.append(expected)
            self.assertGreater(len(set(colors)), 1)

    def test_builtin_and_custom_indicators_use_muted_category_color_families(self):
        from worklogger.domain.worklog.models import CustomWorkMode
        engine = ThemeEngine()
        for dark in (False, True):
            for category, minimum, maximum in (("work", 185, 255), ("leave", 0, 50), ("break", 75, 175)):
                definitions = [item for item in EntryType if item.category == category]
                definitions.extend(CustomEntryType(f"custom:{index:032x}", "Example", category) for index in range(1, 65))
                if category == "work":
                    definitions.extend(CustomWorkMode(f"custom:{index:032x}", "Hybrid") for index in range(1, 17))
                for definition in definitions:
                    color = QColor(engine.entry_type_color(definition, dark=dark))
                    hue, saturation, _lightness, _alpha = color.getHsl()
                    self.assertTrue(minimum <= hue <= maximum, (category, color.name(), hue))
                    self.assertLess(saturation, 170)

    def test_theme_engine_uses_shared_templates_and_resolved_palettes(self) -> None:
        engine = ThemeEngine()

        for theme in ("blue", "pink", "green", "purple", "custom", "liquid_glass"):
            for mode in ("light", "dark"):
                stylesheet = engine.application_stylesheet(theme, dark=mode == "dark")
                self.assertIn("QPushButton", stylesheet)
                self.assertNotIn("{{", stylesheet)
                colors = engine.palette(theme, dark=mode == "dark")
                qt_palette = engine.qt_palette(theme, dark=mode == "dark")
                self.assertEqual(qt_palette.color(QPalette.ColorRole.AlternateBase).name(), colors.table_alternate)
                self.assertEqual(qt_palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText).name(),
                                 colors.disabled_text)

        stylesheet = engine.application_stylesheet("custom", custom_color="#123456")
        self.assertIn("#123456", stylesheet)
        self.assertIn("QPushButton[variant=\"primary\"]", stylesheet)
        self.assertNotIn("{{", stylesheet)


if __name__ == "__main__":
    unittest.main()
