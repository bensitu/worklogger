import os
import unittest
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, QDateTime, QPoint, QTime, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDateEdit, QDateTimeEdit

from worklogger.presentation.widgets.date_picker import MonthCalendar, configure_calendar_popup


class DatePickerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_adjacent_cells_at_supported_year_limits_remain_renderable(self):
        calendar = MonthCalendar()
        try:
            calendar.setDateRange(QDate(1, 1, 1), QDate(9999, 12, 31))
            calendar.show()
            for chosen, endpoint in ((QDate(1, 1, 1), date.min), (QDate(9999, 12, 31), date.max)):
                calendar.setSelectedDate(chosen)
                calendar.setCurrentPage(chosen.year(), chosen.month())
                self.app.processEvents()
                self.assertIn(endpoint, calendar.visible_range())
                self.assertFalse(calendar.grab().isNull())
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
