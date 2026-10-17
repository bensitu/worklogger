from datetime import date, datetime, timezone
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTime

from worklogger.domain.worklog.models import WorkLog
from worklogger.presentation.widgets.record_edit_dialogs import RecordBoundaryDialog


class RecordBoundaryDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from tests.presentation.qt_support import dispose_test_windows
        self.addCleanup(dispose_test_windows)

    def test_typed_time_requires_confirmation_and_can_be_restored_without_saving(self):
        record = WorkLog(1, date(2026, 10, 9), "09:00", "12:00", note="Work", id=1)
        dialog = RecordBoundaryDialog(record)
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()
        self.assertTrue(dialog.date_combo.isHidden())
        editor = dialog.time_input
        editor.setFocus()
        editor.selectAll()
        QTest.keyClicks(editor, "11:30")
        QTest.mouseClick(dialog.status_label, Qt.MouseButton.LeftButton)
        self.assertFalse(dialog.confirm_button.isEnabled())
        self.assertTrue(dialog.apply_time_button.isEnabled())
        self.assertEqual(dialog.preview.topLevelItem(0).text(1), "09:00 - 10:30")
        dialog.accept()
        self.assertEqual(dialog.result(), 0)
        dialog.apply_time_button.click()
        self.assertEqual(dialog.preview.topLevelItem(0).text(1), "09:00 - 11:30")
        self.assertTrue(dialog.confirm_button.isEnabled())
        editor.selectAll()
        QTest.keyClicks(editor, "10:00")
        dialog.reset_time_button.click()
        self.assertEqual(editor.text(), "11:30")
        self.assertEqual(dialog.preview.topLevelItem(1).text(1), "11:30 - 12:00")
        self.assertTrue(dialog.confirm_button.isEnabled())
        editor.setText("25:00")
        self.assertFalse(dialog.apply_time_button.isEnabled())
        self.assertFalse(dialog.confirm_button.isEnabled())
        dialog.reset_time_button.click()
        self.assertEqual(editor.text(), "11:30")
        self.assertTrue(dialog.confirm_button.isEnabled())
        editor.selectAll()
        QTest.keyClicks(editor, "11:45")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.assertEqual(dialog.preview.topLevelItem(0).text(1), "09:00 - 11:45")
        self.assertEqual(dialog.result(), 0)
        dialog.confirm_button.click()
        self.assertEqual(dialog.result(), 1)

    def test_clock_picker_preserves_seconds_and_only_applies_confirmed_selection(self):
        start = datetime(2026, 10, 9, 9, 0, 17, tzinfo=timezone.utc)
        record = WorkLog(1, start.date(), "09:00", "12:00", started_at=start, ended_at=start.replace(hour=12), id=1)
        dialog = RecordBoundaryDialog(record)
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        dialog.time_input.actions()[0].trigger()
        picker = dialog._time_picker
        picker.time_input.setTime(QTime(11, 30, 45))
        picker.reject()
        self.assertEqual(dialog.time_input.text(), "10:30:17")
        dialog.time_input.actions()[0].trigger()
        picker = dialog._time_picker
        picker.time_input.setTime(QTime(11, 30, 45))
        picker.select_button.click()
        self.assertEqual(dialog.time_input.text(), "11:30:45")
        self.assertEqual(dialog.chosen_boundary(), start.replace(hour=11, minute=30, second=45))
        self.assertEqual(dialog.preview.topLevelItem(0).text(1), "09:00:17 - 11:30:45")
        self.assertTrue(dialog.confirm_button.isEnabled())
        dialog.time_input.actions()[0].trigger()
        picker = dialog._time_picker
        picker.time_input.setTime(QTime(23, 59, 45))
        self.assertEqual(picker.time_input.time(), QTime(23, 59, 45))
        picker.reject()
        self.assertEqual(dialog.time_input.text(), "11:30:45")
