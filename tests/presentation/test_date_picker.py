import os
import unittest
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, QDateTime, QPoint, QTime, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDateEdit, QDateTimeEdit

from worklogger.presentation.widgets.date_picker import MonthCalendar, configure_calendar_popup
from worklogger.presentation.widgets.date_range import DateRangeControls
from worklogger.presentation.theme import ThemeEngine


class DatePickerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_date_range_popups_follow_current_and_changed_application_themes(self):
        old_style, old_palette = self.app.styleSheet(), self.app.palette()
        old_context = self.app.property("worklogger_theme_context")
        engine = ThemeEngine()
        engine.apply_to(self.app, "blue", dark=False)
        controls = DateRangeControls(date(2026, 10, 18))
        try:
            controls.show()
            for dark, accent in ((True, "#167780"), (False, "#357428")):
                colors = engine.apply_to(self.app, "custom", dark=dark, custom_color=accent)
                controls.period_button.click()
                self.app.processEvents()
                calendars = (controls.period_button.calendar, controls.start_input.calendarWidget(),
                             controls.end_input.calendarWidget())
                for calendar in calendars:
                    self.assertIsInstance(calendar, MonthCalendar)
                    weekend_color = calendar.weekdayTextFormat(Qt.DayOfWeek.Saturday).foreground().color().name()
                    self.assertEqual(weekend_color, colors.accent)
                month = 11 if dark else 12
                selected = QDate(2026, month, 21)
                controls.period_button.calendar.setSelectedDate(selected)
                controls.period_button.calendar.clicked.emit(selected)
                self.assertEqual(controls.bounds(), (date(2026, month, 1), date(2026, month, 30 if dark else 31)))
                self.assertFalse(controls.period_button.calendar.isVisible())
        finally:
            controls.close()
            controls.deleteLater()
            self.app.processEvents()
            self.app.setStyleSheet(old_style)
            self.app.setPalette(old_palette)
            self.app.setProperty("worklogger_theme_context", old_context)

    def test_visible_range_matches_painted_cells_and_supported_year_limits(self):
        calendar = MonthCalendar()
        try:
            calendar.setDateRange(QDate(1, 1, 1), QDate(9999, 12, 31))
            calendar.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
            calendar.show()
            for chosen, endpoint in ((QDate(2026, 6, 1), date(2026, 5, 25)),
                                     (QDate(1, 1, 1), date.min), (QDate(9999, 12, 31), date.max)):
                calendar.setSelectedDate(chosen)
                calendar.setCurrentPage(chosen.year(), chosen.month())
                self.app.processEvents()
                self.assertIn(endpoint, calendar.visible_range())
                self.assertFalse(calendar.grab().isNull())
                self.assertEqual(calendar.visible_range(), (min(calendar._cell_rects), max(calendar._cell_rects)))
        finally:
            calendar.close()
            calendar.deleteLater()

    def test_popup_selection_preserves_field_ranges_and_time_components(self):
        for field in (QDateEdit(), QDateTimeEdit()):
            with self.subTest(field=type(field).__name__):
                try:
                    field.setDisplayFormat("yyyy-MM-dd HH:mm:ss" if type(field) is QDateTimeEdit else "yyyy-MM-dd")
                    field.setDateRange(QDate(2026, 10, 1), QDate(2026, 10, 31))
                    field.setDateTime(QDateTime(QDate(2026, 10, 10), QTime(12, 34, 56)))
                    original = field.dateTime()
                    calendar = configure_calendar_popup(field)
                    self.assertEqual(field.dateTime(), original)
                    self.assertEqual(calendar.minimumDate(), field.minimumDate())
                    self.assertEqual(calendar.maximumDate(), field.maximumDate())
                    field.resize(300, 42)
                    field.show()
                    self.assertTrue(QTest.qWaitForWindowExposed(field))
                    QTest.mouseClick(field, Qt.MouseButton.LeftButton,
                                     pos=QPoint(field.width() - 12, field.height() // 2))
                    self.app.processEvents()
                    self.assertTrue(calendar.isVisible())
                    self.assertEqual(calendar.selectedDate(), field.date())
                    chosen = QDate(2026, 10, 12)
                    calendar.setSelectedDate(chosen)
                    calendar.clicked.emit(chosen)
                    self.assertEqual(field.date(), chosen)
                    self.assertEqual(field.time(), original.time())
                    self.assertFalse(calendar.window().isVisible())
                finally:
                    field.close()
                    field.deleteLater()
