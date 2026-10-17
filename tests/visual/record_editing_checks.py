"""Opt-in rendering checks for time selection and replacement timelines."""

from dataclasses import replace
from datetime import date
import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QPoint
from PySide6.QtWidgets import QApplication

from worklogger.domain.worklog.models import WorkLog, EntryType
from worklogger.domain.worklog.replacement import EntryReplacement
from worklogger.infrastructure.i18n import available_languages, get_language, set_language
from worklogger.presentation.theme import ThemeEngine, configure_application_style, install_bundled_fonts
from worklogger.presentation.widgets.record_edit_dialogs import OverlapReplacementDialog, RecordBoundaryDialog


class RecordEditingLayoutChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        configure_application_style()
        install_bundled_fonts()

    def test_time_controls_and_timelines_fit_languages_and_color_modes(self):
        old_language = get_language()
        old_palette, old_style = self.app.palette(), self.app.styleSheet()
        old_context = self.app.property("worklogger_theme_context")
        day = date(2026, 12, 31)
        morning = WorkLog(1, day, "09:00", "12:00", note="Planning", entry_type=EntryType.MEETING, id=1)
        afternoon = WorkLog(1, day, "13:00", "18:00", note="Review", entry_type=EntryType.REMOTE, id=2)
        incoming = WorkLog(1, day, "11:00", "14:00", note="Rest", entry_type=EntryType.BREAK)
        try:
            for language in available_languages():
                set_language(language)
                for theme, dark in (("liquid_glass", False), ("blue", True)):
                    ThemeEngine().apply_to(self.app, theme, dark=dark)
                    prefix = f"{language}-{theme}"
                    overlap = OverlapReplacementDialog(EntryReplacement(incoming, (morning, afternoon)))
                    boundary = RecordBoundaryDialog(morning)
                    overnight = RecordBoundaryDialog(replace(morning, start_time="22:00", end_time="06:00", entry_type=EntryType.BREAK))
                    historical = OverlapReplacementDialog(EntryReplacement(incoming, (replace(morning, break_hours=1), afternoon)))
                    for dialog, name in ((boundary, "split"), (overnight, "overnight"), (overlap, "overlap"), (historical, "historical")):
                        try:
                            dialog.show()
                            self.app.processEvents()
                            self.assertEqual(dialog.confirm_button.isEnabled(), dialog is not historical)
                            self.assertTrue(dialog.rect().contains(dialog.confirm_button.geometry()))
                            if dialog is overlap:
                                self.assertTrue(all(not dialog.status_stack.widget(index).text().strip()
                                                    for index in range(dialog.status_stack.count())))
                                self.assertEqual(overlap.keep_button.y(), overlap.whole_button.y())
                                for choice in (overlap.keep_button, overlap.whole_button):
                                    self.assertLessEqual(choice.fontMetrics().horizontalAdvance(choice.text()) + 24, choice.width())
                                timeline = overlap.timeline
                                left, right = [timeline.period_rect(item) for item in timeline._existing]
                                new = timeline.period_rect(timeline._incoming, incoming=True)
                                self.assertAlmostEqual(left.width() / right.width(), 3 / 5)
                                self.assertLess(left.right(), right.left())
                                self.assertLess(new.bottom(), left.top())
                                before = timeline.grab().toImage().scaled(timeline.size())
                                stable_bounds = self.overlap_geometry(dialog)
                                self.assert_message_fit(dialog)
                                self.capture(dialog, prefix + "-overlap-partial")
                                overlap.whole_button.click()
                                self.app.processEvents()
                                self.assertEqual(self.overlap_geometry(dialog), stable_bounds)
                                self.assert_message_fit(dialog)
                                overlap.keep_button.click()
                                self.app.processEvents()
                                self.assertEqual(self.overlap_geometry(dialog), stable_bounds)
                                overlap.whole_button.click()
                                self.app.processEvents()
                                after = timeline.grab().toImage().scaled(timeline.size())
                                self.assertNotEqual(before.pixelColor(left.topLeft().toPoint() + QPoint(5, 5)),
                                                    after.pixelColor(left.topLeft().toPoint() + QPoint(5, 5)))
                                self.assertEqual(before.pixelColor(new.topLeft().toPoint() + QPoint(5, 5)),
                                                 after.pixelColor(new.topLeft().toPoint() + QPoint(5, 5)))
                            elif dialog is historical:
                                stable_bounds = self.overlap_geometry(dialog)
                                self.assert_message_fit(dialog)
                                historical.whole_button.click()
                                self.app.processEvents()
                                self.assertTrue(dialog.confirm_button.isEnabled())
                                self.assertEqual(dialog.status_stack.currentWidget().text().strip(), "")
                                self.assertEqual(self.overlap_geometry(dialog), stable_bounds)
                                self.assert_message_fit(dialog)
                                historical.keep_button.click()
                                self.app.processEvents()
                                self.assertFalse(dialog.confirm_button.isEnabled())
                                self.assertEqual(self.overlap_geometry(dialog), stable_bounds)
                            else:
                                fields = (dialog.time_input, dialog.apply_time_button, dialog.reset_time_button)
                                if dialog is overnight:
                                    fields += (dialog.date_combo,)
                                self.assertEqual({widget.height() for widget in fields}, {dialog.apply_time_button.height()})
                                self.assertEqual({widget.y() for widget in fields}, {dialog.apply_time_button.y()})
                                self.assertEqual(dialog.status_label.text(), "")
                                for control in (dialog.time_input, dialog.apply_time_button, dialog.reset_time_button):
                                    bounds = control.rect().translated(control.mapTo(dialog, control.rect().topLeft()))
                                    self.assertTrue(dialog.rect().contains(bounds))
                            self.capture(dialog, prefix + "-" + name)
                        finally:
                            dialog.hide()
                            dialog.deleteLater()
                    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        finally:
            set_language(old_language)
            self.app.setPalette(old_palette)
            self.app.setStyleSheet(old_style)
            self.app.setProperty("worklogger_theme_context", old_context)

    def assert_message_fit(self, dialog):
        for stack in (dialog.message_stack, dialog.status_stack):
            for index in range(stack.count()):
                self.assertLessEqual(stack.widget(index).heightForWidth(stack.width()), stack.height())

    @staticmethod
    def overlap_geometry(dialog):
        return tuple(widget.geometry() for widget in (
            dialog.message_stack, dialog.timeline, dialog.preview, dialog.status_stack, dialog.confirm_button))

    @staticmethod
    def capture(dialog, name):
        destination = os.environ.get("WORKLOGGER_SCREENSHOTS")
        if destination:
            path = Path(destination)
            path.mkdir(parents=True, exist_ok=True)
            dialog.grab().save(str(path / (name + ".png")))
