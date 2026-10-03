from contextlib import contextmanager
from dataclasses import replace
from datetime import date
import os
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QTime
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QApplication, QDialog, QLabel

from worklogger.app.use_cases.calendar import GetCalendarEventsForRangeHandler
from worklogger.app.use_cases.work_logs import GetMonthRecordsHandler
from worklogger.domain.calendar.models import CalendarEvent
from worklogger.domain.worklog.models import WorkLog, WorkType
from worklogger.infrastructure.i18n import _, available_languages, set_language
from worklogger.infrastructure.repositories import SQLiteCalendarEventRepository, SQLiteWorkLogRepository
from worklogger.presentation.viewmodels import CalendarViewModel
from worklogger.presentation.theme.fonts import install_bundled_fonts
from worklogger.presentation.widgets.sidebar import SidebarWidget
from worklogger.presentation.widgets.calendar import CalendarDayButton, _holiday_lines
from tests.presentation.test_app_window import MemoryCalendarRepository, MemoryWorkLogRepository, _window


class ReadOnlyDatabase:
    def __init__(self, path):
        self.path = Path(path).resolve()

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()


def may_records():
    records = MemoryWorkLogRepository()
    events = tuple(CalendarEvent(
        index, 1, date(2026, 5, 21), f"Meeting {index}", "13:00", "14:00",
    ) for index in range(1, 7))
    for day in range(1, 32):
        if date(2026, 5, day).weekday() < 5:
            records.save(WorkLog(1, date(2026, 5, day), "09:00", "18:30", 1.0,
                                 "Feature work", WorkType.NORMAL))
    records.save(WorkLog(1, date(2026, 5, 21), "22:00", "07:30", 1.0,
                         "Night shift", WorkType.BUSINESS_TRIP))
    selected = date(2026, 5, 21)
    database = os.environ.get("WORKLOGGER_QA_DATABASE")
    if database:
        factory = ReadOnlyDatabase(database)
        with factory.connection() as connection:
            row = connection.execute(
                "SELECT user_id FROM worklog WHERE d BETWEEN ? AND ? GROUP BY user_id ORDER BY COUNT(*) DESC",
                ("2026-05-01", "2026-05-31"),
            ).fetchone()
        if row is None:
            raise AssertionError("The QA database contains no May 2026 work logs")
        user_id = row["user_id"]
        imported = SQLiteWorkLogRepository(factory).list_for_month(user_id, 2026, 5)
        records.records.clear()
        for record in imported:
            records.save(replace(record, user_id=1))
        events = tuple(replace(event, user_id=1) for event in
                       SQLiteCalendarEventRepository(factory).list_for_range(user_id, date(2026, 5, 1), date(2026, 5, 31)))
        if records.get_for_day(1, selected) is None:
            selected = imported[-1].day
    return records, events, selected


class CalendarLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        set_language("en_US")

    def test_hour_rows_keep_identical_positions_with_or_without_holidays(self):
        install_bundled_fonts()
        records = MemoryWorkLogRepository()
        day = date(2026, 5, 13)
        records.save(WorkLog(1, day, "09:00", "20:00", 1.0))
        model = CalendarViewModel(user_id=1, month_records_handler=GetMonthRecordsHandler(records))
        names = ("", "Holiday", "International Workers Memorial Day", "国際労働者記念日の追加情報")
        for dark in (False, True):
            for selected in (False, True):
                state = model.build_month(
                    year=2026, month=5, selected_day=day if selected else date(2026, 5, 1),
                    today=date(2026, 5, 1), holidays={}, dark=dark,
                ).value
                cell = next(cell for cell in state.cells if cell.day == day)
                button = CalendarDayButton()
                try:
                    for width, height in ((90, 90), (120, 120), (160, 180)):
                        button.resize(width, height)
                        expected = None
                        for name in names:
                            with self.subTest(dark=dark, selected=selected, size=(width, height), name=name):
                                button.set_cell(replace(cell, holiday_name=name, is_holiday=bool(name)))
                                rendered = button.grab().toImage()
                                scale = rendered.devicePixelRatio()
                                hours = rendered.copy(round(8 * scale), round(54 * scale),
                                                      round((width - 16) * scale), round((height - 58) * scale))
                                if expected is None:
                                    expected = hours
                                    self.assertGreater(len({hours.pixel(x, y) for x in range(hours.width())
                                                            for y in range(hours.height())}), 1)
                                else:
                                    self.assertEqual(hours, expected)
                finally:
                    button.close()
                    button.deleteLater()

    def test_holiday_names_wrap_to_two_lines_and_keep_long_names_in_tooltips(self):
        font = QFont("Noto Sans")
        font.setPixelSize(11)
        for text in ("International Workers Memorial Day", "国際労働者記念日の追加情報", "국제 노동자 기념일 추가 정보", "国际劳动者纪念日的附加说明"):
            lines = _holiday_lines(text, font, 60)
            self.assertEqual(len(lines), 2)
            self.assertTrue(all(QFontMetrics(font).horizontalAdvance(line) <= 60 for line in lines))
        self.assertEqual(_holiday_lines("", font, 60), ())

    def test_last_day_is_accessible_without_shrinking_cells_or_right_panel(self):
        records, _events, _selected = may_records()
        window = _window(records)
        window._current_month = date(2026, 5, 1)
        window._selected_day = date(2026, 5, 1)
        window._holidays = {date(2026, 5, 31): "International Workers Memorial Day"}
        window.resize(880, 580)
        window.show()
        try:
            self.assertTrue(window.refresh())
            self.app.processEvents()
            self.assertTrue(window.select_day(date(2026, 5, 31)))
            self.app.processEvents()
            scroll = window.calendar_page.calendar_scroll
            self.assertGreater(scroll.verticalScrollBar().maximum(), 0)
            self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
            selected = next(button for button in window.calendar_view.day_buttons() if button.cell.is_selected)
            position = selected.mapTo(scroll.viewport(), QPoint())
            self.assertGreaterEqual(position.y(), 0)
            self.assertLessEqual(position.y() + selected.height(), scroll.viewport().height())
            self.assertGreaterEqual(selected.height(), 90)
            self.assertIn("International Workers Memorial Day", selected.toolTip())
            self.assertEqual(window.calendar_page.details_scroll.verticalScrollBar().maximum(), 0)
            self.assertEqual((window.width(), window.height()), (880, 580))
        finally:
            window.close()

    def test_sidebar_avatar_is_round_without_product_label(self):
        sidebar = SidebarWidget(account_name="Sample User")
        self.assertIsNone(sidebar.findChild(QLabel, "sidebar_product_label"))
        avatar = sidebar.profile_avatar_label.pixmap().toImage()
        for x, y in ((0, 0), (71, 0), (0, 71), (71, 71)):
            self.assertEqual(avatar.pixelColor(x, y).alpha(), 0)
        self.assertGreater(avatar.pixelColor(36, 36).alpha(), 0)
        sidebar.close()

    def test_time_picker_fits_and_keeps_translations_and_cancel_behavior(self):
        for language in available_languages():
            set_language(language)
            for dark in (False, True):
                with self.subTest(language=language, dark=dark):
                    window = _window(MemoryWorkLogRepository(), confirm_discard_changes=lambda: True)
                    window._config = replace(window._config, dark=dark)
                    window.apply_theme()
                    window.resize(880, 580)
                    window.show()
                    try:
                        self.assertTrue(window.refresh())
                        panel = window.entry_panel
                        panel.start_input.setText("0930")
                        draft = panel.current_draft()
                        panel.start_time_action.trigger()
                        self.app.processEvents()
                        dialog = next(child for child in panel.findChildren(QDialog) if child.isVisible())
                        self.assertEqual(dialog.windowTitle(), _("Start"))
                        self.assertEqual(dialog.select_button.text(), _("Select"))
                        self.assertEqual(dialog.close_button.text(), _("Close"))
                        self.assertEqual(dialog.time_input.time(), QTime(9, 30))
                        for widget in (dialog.time_input, dialog.select_button, dialog.close_button):
                            self.assertTrue(dialog.rect().contains(widget.geometry()))
                            self.assertGreaterEqual(widget.height(), widget.fontMetrics().height() + 10)
                        directory = os.environ.get("WORKLOGGER_SCREENSHOTS")
                        if directory:
                            target = Path(directory)
                            target.mkdir(parents=True, exist_ok=True)
                            self.assertTrue(dialog.grab().save(str(target / f"{language}-time-picker-{'dark' if dark else 'light'}.png")))
                        dialog.close_button.click()
                        self.assertEqual(panel.current_draft(), draft)
                    finally:
                        window.close()

    def test_compact_notes_and_auto_record_remain_available(self):
        records = MemoryWorkLogRepository()
        records.save(WorkLog(1, date(2026, 4, 20), "09:00", "18:00", 1.0, "Original note"))
        window = _window(records)
        window.refresh()
        window.show()
        window.resize(880, 580)
        panel = window.entry_panel
        try:
            self.assertFalse(panel.note_input.isVisible())
            panel.note_toggle_button.setChecked(True)
            self.app.processEvents()
            self.assertEqual(panel.note_input.toPlainText(), "Original note")
            panel.note_input.setPlainText("Updated note")
            panel.note_toggle_button.setChecked(False)
            with patch("worklogger.presentation.shell.app_window.QMessageBox.information") as notification:
                panel.save_button.click()
            notification.assert_not_called()
            self.assertEqual(records.get_for_day(1, date(2026, 4, 20)).note, "Updated note")
            panel.time_tabs.setCurrentIndex(1)
            self.app.processEvents()
            self.assertEqual((window.width(), window.height()), (880, 580))
            self.assertEqual(window.calendar_page.details_scroll.horizontalScrollBar().maximum(), 0)
            for button in (panel.clock_in_button, panel.clock_out_button, panel.break_button, panel.quick_break_button):
                self.assertTrue(button.isVisible())
                self.assertTrue(panel.auto_tab.rect().contains(button.geometry()))
            self.assertEqual(panel.current_draft().note, "Updated note")
        finally:
            window.close()

    def test_calendar_right_panel_fits_and_keeps_notes_and_records_accessible(self):
        records, events, selected = may_records()
        for language in available_languages():
            set_language(language)
            for dark in (False, True):
                window = _window(records, account_name="Sample User")
                window._config = replace(window._config, dark=dark, selected_day=selected)
                window._selected_day = selected
                window._current_month = date(2026, 5, 1)
                window._today = date(2026, 5, 15)
                window._holidays = {date(2026, 5, 21): "International Workers Memorial Day"}
                window._calendar_view_model = CalendarViewModel(
                    user_id=1, month_records_handler=GetMonthRecordsHandler(records),
                    calendar_events_handler=GetCalendarEventsForRangeHandler(MemoryCalendarRepository(events)),
                )
                window.apply_theme()
                self.assertTrue(window.refresh())
                window.show()
                try:
                    for width, height in ((880, 580), (1100, 700)):
                        with self.subTest(language=language, dark=dark, width=width):
                            window.resize(width, height)
                            self.app.processEvents()
                            self.assertEqual((window.width(), window.height()), (width, height))
                            panel = window.entry_panel
                            self.assertFalse(panel.note_input.isVisible())
                            fields = (panel.start_input, panel.end_input, panel.break_input, panel.work_type_combo)
                            self.assertEqual(len({field.mapTo(panel, QPoint()).x() for field in fields}), 1)
                            for field in (*fields, panel.save_button):
                                position = field.mapTo(window.calendar_page.details_scroll.viewport(), QPoint())
                                self.assertGreaterEqual(position.y(), 0)
                                self.assertLessEqual(position.y() + field.height(), window.calendar_page.details_scroll.viewport().height())
                            self.assertEqual(window.calendar_page.details_scroll.horizontalScrollBar().maximum(), 0)
                            self.assertEqual(window.calendar_page.details_scroll.verticalScrollBar().maximum(), 0)
                            self.assertGreaterEqual(window.calendar_page.records_scroll.height(), 96)
                            self.assertEqual(sum(button.isVisible() for button in window.calendar_view.day_buttons()), 31)
                            self.assertTrue(all(button.height() >= 90 for button in window.calendar_view.day_buttons() if button.isVisible()))
                            self.assertEqual(window.calendar_page.calendar_scroll.horizontalScrollBar().maximum(), 0)
                            self.assertTrue(all(not label.isVisible() for label in window.calendar_view.week_total_labels()))
                            self.assertEqual(panel.current_draft().note, records.get_for_day(1, selected).note)
                            labels = window.calendar_page.records_widget.findChildren(QLabel, "calendar_record_label")
                            self.assertEqual(len(labels), sum(event.day == selected for event in events) + 1)
                            self.assertTrue(all(label.textFormat().name == "PlainText" for label in labels))
                            directory = os.environ.get("WORKLOGGER_SCREENSHOTS")
                            if directory:
                                target = Path(directory)
                                target.mkdir(parents=True, exist_ok=True)
                                self.assertTrue(window.grab().save(str(target / f"{language}-calendar-may-{'dark' if dark else 'light'}-{width}.png")))
                            panel.note_toggle_button.setChecked(True)
                            self.app.processEvents()
                            self.assertTrue(panel.note_input.isVisible())
                            panel.note_toggle_button.setChecked(False)
                            self.app.processEvents()
                    if events:
                        self.assertTrue(window.select_day(events[0].day))
                        self.app.processEvents()
                        event_labels = window.calendar_page.records_widget.findChildren(QLabel, "calendar_record_label")
                        self.assertTrue(any(events[0].summary in label.text() for label in event_labels))
                finally:
                    window.close()


if __name__ == "__main__":
    unittest.main()
