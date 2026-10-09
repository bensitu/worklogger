from contextlib import contextmanager
from dataclasses import replace
from datetime import date
import os
from pathlib import Path
import sqlite3
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QFrame

from worklogger.domain.calendar.models import CalendarEvent
from worklogger.domain.worklog.models import WorkLog, WorkType
from worklogger.infrastructure.i18n import available_languages, set_language
from worklogger.infrastructure.repositories import SQLiteCalendarEventRepository, SQLiteWorkLogRepository
from tests.presentation.test_app_window import MemoryWorkLogRepository, _window


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


class CalendarLayoutChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        set_language("en_US")

    def test_custom_type_manager_fits_long_names_and_accounting_controls(self):
        import tempfile
        from worklogger.app.use_cases.work_types import WorkTypeService
        from worklogger.infrastructure.database import SQLiteConnectionFactory, MigrationRunner
        from worklogger.infrastructure.repositories import SQLiteAuthRepository
        from worklogger.infrastructure.repositories.work_type_sqlite import SQLiteWorkTypeRepository
        from worklogger.infrastructure.security import PBKDF2PasswordHasher
        from worklogger.presentation.widgets.work_type_manager import WorkTypeManagerDialog
        from worklogger.presentation.theme import ThemeEngine, configure_application_style, install_bundled_fonts

        configure_application_style()
        install_bundled_fonts()

        with tempfile.TemporaryDirectory() as directory:
            factory = SQLiteConnectionFactory(Path(directory) / "types.db")
            MigrationRunner(factory).run_pending()
            user = SQLiteAuthRepository(factory, password_hasher=PBKDF2PasswordHasher(iterations=1000)).create_user(
                "sample", "example-password", recovery_key=None, is_admin=False)
            service = WorkTypeService(user.id, SQLiteWorkTypeRepository(factory))
            service.save("Research and development across international product teams", "work")
            service.save("Lunch", "break")
            service.save("Personal leave", "leave")

            class Model:
                def list_work_types(self):
                    return service.list_types()
                def save_work_type(self, label, category, previous=None):
                    return service.save(label, category, previous)
                def archive_work_type(self, definition):
                    return service.archive(definition)

            engine = ThemeEngine()
            for language, dark in (("en_US", False), ("zh_CN", True)):
                set_language(language)
                self.app.setPalette(engine.qt_palette(dark=dark))
                self.app.setStyleSheet(engine.application_stylesheet(dark=dark))
                dialog = WorkTypeManagerDialog(Model())
                try:
                    dialog.show()
                    self.app.processEvents()
                    self.assertEqual((dialog.width(), dialog.height()), (700, 420))
                    dialog.type_list.setCurrentRow(0)
                    self.assertTrue(dialog.name_input.text())
                    for control in (dialog.type_list, dialog.name_input, dialog.category_combo,
                                    dialog.save_button, dialog.new_button, dialog.archive_button, dialog.close_button):
                        self.assertTrue(dialog.rect().contains(control.rect().translated(control.mapTo(dialog, QPoint()))))
                    destination = os.environ.get("WORKLOGGER_SCREENSHOTS")
                    if destination:
                        Path(destination).mkdir(parents=True, exist_ok=True)
                        self.assertTrue(dialog.grab().save(str(Path(destination) / f"{language}-work-types.png")))
                finally:
                    dialog.hide()
                    dialog.deleteLater()


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
            self.assertTrue(window.entry_panel.actions_widget.isVisibleTo(window.calendar_page))
            self.assertEqual((window.width(), window.height()), (880, 580))
        finally:
            window.close()


    def test_calendar_right_panel_fits_and_keeps_notes_and_records_accessible(self):
        records, events, selected = may_records()
        for language in available_languages():
            set_language(language)
            for dark in ((False, True) if language == "en_US" else (language in ("ja_JP", "zh_TW"),)):
                window = _window(records, account_name="Sample User", calendar_events=events)
                window._config = replace(window._config, dark=dark, selected_day=selected)
                window._selected_day = selected
                window._current_month = date(2026, 5, 1)
                window._today = date(2026, 5, 15)
                window._holidays = {date(2026, 5, 21): "International Workers Memorial Day"}
                window.apply_theme()
                self.assertTrue(window.refresh())
                window.show()
                try:
                    sizes = ((880, 580), (1100, 700)) if language == "en_US" else ((880, 580),)
                    for width, height in sizes:
                        with self.subTest(language=language, dark=dark, width=width):
                            window.resize(width, height)
                            self.app.processEvents()
                            self.assertEqual((window.width(), window.height()), (width, height))
                            panel = window.entry_panel
                            right = window.calendar_page.findChild(QFrame, "calendar_right_panel_frame")
                            self.assertGreater(window.calendar_page.calendar_scroll.width(), right.width())
                            self.assertTrue(panel.content_input.isVisible())
                            fields = (panel.start_input, panel.end_input)
                            self.assertEqual(fields[0].mapTo(window, QPoint()).y(), fields[1].mapTo(window, QPoint()).y())
                            for field in fields:
                                rect = field.rect().translated(field.mapTo(panel.time_tabs.currentWidget(), QPoint()))
                                self.assertTrue(panel.time_tabs.currentWidget().rect().contains(rect))
                            for field in (*fields, panel.save_button, panel.clear_button, window.calendar_page.selected_date_label):
                                position = field.mapTo(window.calendar_page, QPoint())
                                self.assertGreaterEqual(position.y(), 0)
                                self.assertLessEqual(position.y() + field.height(), window.calendar_page.height())
                            self.assertEqual(window.calendar_page.details_scroll.horizontalScrollBar().maximum(), 0)
                            self.assertGreaterEqual(window.calendar_page.records_scroll.height(), 96)
                            self.assertEqual(sum(button.isVisible() for button in window.calendar_view.day_buttons()), 31)
                            self.assertTrue(all(button.height() >= 90 for button in window.calendar_view.day_buttons() if button.isVisible()))
                            self.assertEqual(window.calendar_page.calendar_scroll.horizontalScrollBar().maximum(), 0)
                            self.assertTrue(all(not label.isVisible() for label in window.calendar_view.week_total_labels()))
                            history = window.calendar_page.records_widget
                            self.assertEqual(len(history.event_buttons), sum(event.day == selected for event in events))
                            self.assertEqual(len(history.entry_buttons), 1)
                            directory = os.environ.get("WORKLOGGER_SCREENSHOTS")
                            if directory:
                                target = Path(directory)
                                target.mkdir(parents=True, exist_ok=True)
                                self.assertTrue(window.grab().save(str(target / f"{language}-calendar-may-{'dark' if dark else 'light'}-{width}.png")))
                            panel.time_tabs.setCurrentIndex(1)
                            self.app.processEvents()
                            self.assertTrue(panel.clock_in_button.isVisible())
                            for button in (panel.clock_in_button, panel.clock_out_button, panel.break_button, panel.discard_timer_button):
                                self.assertLessEqual(button.fontMetrics().horizontalAdvance(button.text()) + (24 if not button.icon().isNull() else 0) + 18, button.width())
                            self.assertTrue(panel.actions_widget.isVisible())
                            panel.time_tabs.setCurrentIndex(0)
                            self.app.processEvents()
                    if events:
                        self.assertTrue(window.select_day(events[0].day))
                        self.app.processEvents()
                        event_buttons = window.calendar_page.records_widget.event_buttons.values()
                        self.assertTrue(any(events[0].summary in button.label.text() for button in event_buttons))
                finally:
                    window.close()


if __name__ == "__main__":
    unittest.main()
