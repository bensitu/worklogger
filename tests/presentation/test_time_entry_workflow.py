from datetime import date, datetime, timedelta
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMessageBox, QPushButton
from PySide6.QtGui import QCloseEvent

from worklogger.bootstrap import DesktopRuntimeConfig, build_desktop_runtime
from worklogger.infrastructure.language_preferences import LanguagePreferences
from worklogger.infrastructure.repositories.worklog_sqlite import SQLiteWorkLogRepository
from worklogger.infrastructure.repositories.calendar_sqlite import SQLiteCalendarEventRepository
from worklogger.domain.calendar.models import CalendarEvent
from worklogger.presentation.shell.app_window import AppWindowConfig
from worklogger.presentation.job_runner import ImmediateJobRunner, QtJobRunner


class TimeEntryWorkflowTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.enterContext(patch("worklogger.bootstrap.LanguagePreferences", side_effect=lambda:
            LanguagePreferences(QSettings(str(root / "language.ini"), QSettings.Format.IniFormat))))
        self.enterContext(patch.dict(os.environ, {"WORKLOGGER_LANG": "en_US"}))
        self.warning = self.enterContext(patch("worklogger.presentation.widgets.time_entries.QMessageBox.warning"))
        result = build_desktop_runtime(DesktopRuntimeConfig(database_path=root / "worklog.db",
            create_user_if_empty=True, password_iterations=1000,
            window=AppWindowConfig(selected_day=date(2026, 5, 20), today=date(2026, 5, 20),
                                   confirm_discard_changes=lambda: True)), argv=[])
        self.assertTrue(result.ok, result.error)
        self.runtime = result.value
        self.window = result.value.window
        self.addCleanup(self.window.close)
        self.panel = self.window.entry_panel
        self.panel._job_runner = ImmediateJobRunner()
        self.repository = SQLiteWorkLogRepository(result.value.connection_factory)
        self.now = datetime(2026, 5, 20, 9, tzinfo=self.panel.view_model.service.local_timezone)
        self.panel.view_model.service._clock = lambda: self.now
        self.assertTrue(self.window.refresh())

    def test_manual_create_select_update_and_delete_periods(self):
        panel = self.panel
        self.assertEqual(panel.work_type_combo.itemData(panel.work_type_combo.count() - 1), "other")
        for start, end, kind, content in (("09:00", "11:00", "meeting", "Planning"),
                                         ("11:00", "12:00", "training", "Practice")):
            panel.start_input.setText(start)
            panel.end_input.setText(end)
            panel.work_type_combo.setCurrentIndex(panel.work_type_combo.findData(kind))
            panel.content_input.setPlainText(content)
            panel.save_button.click()
            self.assertEqual(panel.work_type_combo.currentData(), "normal")
            self.assertEqual(panel.start_input.text(), end)
        entries = self.repository.list_for_day(self.runtime.user.id, self.now.date())
        self.assertEqual(len(entries), 2)
        self.assertEqual([entry.work_type.value for entry in entries], ["meeting", "training"])
        records = self.window.calendar_page.findChildren(QPushButton, "calendar_time_entry_button")
        self.assertEqual(len([button for button in records if button.parent() is self.window.calendar_page.records_widget]), 2)
        current = next(button for button in records if button.parent() is self.window.calendar_page.records_widget)
        current.click()
        self.assertEqual(panel.view_model.draft.original.id, entries[0].id)
        self.assertEqual(panel.work_type_combo.currentData(), "meeting")
        panel.content_input.setPlainText("Updated planning")
        panel.save_button.click()
        self.assertEqual(len(self.repository.list_for_day(self.runtime.user.id, self.now.date())), 2)
        self.assertEqual(panel.work_type_combo.currentData(), "normal")
        saved = self.repository.get_entry(self.runtime.user.id, entries[0].id)
        self.assertEqual(saved.note, "Updated planning")
        panel.edit_entry(saved)
        panel.content_input.setPlainText("Unsubmitted change")
        panel.clear_button.click()
        self.assertEqual((panel.start_input.text(), panel.end_input.text(), panel.content_input.toPlainText()), ("", "", ""))
        self.assertIsNone(panel.view_model.draft.original)
        self.assertEqual(self.repository.get_entry(self.runtime.user.id, saved.id).note, "Updated planning")
        panel.edit_entry(saved)
        self.window.calendar_page.add_entry_button.click()
        self.assertIsNone(panel.view_model.draft.original)
        self.assertEqual(panel.time_tabs.currentIndex(), 0)
        self.assertEqual((panel.start_input.text(), panel.end_input.text()), ("", ""))
        self.assertEqual(len(self.repository.list_for_day(self.runtime.user.id, self.now.date())), 2)
        card = next(button for button in self.window.calendar_page.records_widget.findChildren(QPushButton, "calendar_time_entry_button")
                    if button.property("entry_id") == saved.id)
        with patch("worklogger.presentation.widgets.time_entries.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            card.delete_button.click()
        self.assertEqual(len(self.repository.list_for_day(self.runtime.user.id, self.now.date())), 1)
        self.warning.assert_not_called()

    def test_storage_jobs_keep_edits_and_shutdown_serialized_off_the_ui_thread(self):
        panel = self.panel
        panel._job_runner = QtJobRunner(self.window)
        self.addCleanup(lambda: panel._job_runner.shutdown(wait=True))
        repository = panel.view_model.service.repository
        save = repository.save_entry
        release = threading.Event()
        threads = []

        def delayed(record, **kwargs):
            threads.append(threading.get_ident())
            release.wait(3)
            return save(record, **kwargs)

        panel.start_input.setText("09:00")
        panel.end_input.setText("10:00")
        with patch.object(repository, "save_entry", side_effect=delayed):
            panel.save_button.click()
            self.assertTrue(panel.is_busy)
            self.assertFalse(panel.isEnabled())
            event = QCloseEvent()
            with patch("worklogger.presentation.shell.app_window.QMessageBox.information"):
                self.window.closeEvent(event)
            self.assertFalse(event.isAccepted())
            release.set()
            deadline = time.monotonic() + 5
            while panel.is_busy and time.monotonic() < deadline:
                self.runtime.application.processEvents()
                time.sleep(0.01)
            self.assertFalse(panel.is_busy)
        self.assertNotEqual(threads[0], threading.get_ident())
        self.assertEqual(len(self.repository.list_for_day(self.runtime.user.id, self.now.date())), 1)

    def test_automatic_break_finish_and_content_save_have_distinct_effects(self):
        panel = self.panel
        panel.time_tabs.setCurrentIndex(1)
        panel.work_type_combo.setCurrentIndex(panel.work_type_combo.findData("meeting"))
        panel.content_input.setPlainText("Planning")
        panel.clock_in_button.click()
        panel.content_input.setPlainText("Agenda")
        panel.save_button.click()
        self.assertEqual(self.repository.list_for_day(self.runtime.user.id, self.now.date()), ())
        self.assertEqual(panel.view_model.service.timer.content, "Agenda")
        self.assertEqual(panel.work_type_combo.currentData(), "meeting")
        panel.clear_button.click()
        self.assertIsNotNone(panel.view_model.service.timer)
        self.assertEqual(panel.view_model.service.timer.content, "Agenda")
        self.assertEqual(panel.content_input.toPlainText(), "")
        panel.content_input.setPlainText("Agenda")
        self.now += timedelta(hours=3)
        panel.break_button.click()
        self.assertEqual(len(self.repository.list_for_day(self.runtime.user.id, self.now.date())), 1)
        self.now += timedelta(hours=1, minutes=15)
        panel._tick()
        self.assertEqual(panel.view_model.service.timer.work_type.value, "meeting")
        self.now = self.now.replace(hour=16, minute=0)
        panel.content_input.setPlainText("Review")
        panel.clock_out_button.click()
        self.assertEqual(panel.work_type_combo.currentData(), "normal")
        entries = self.repository.list_for_day(self.runtime.user.id, self.now.date())
        self.assertEqual(len(entries), 3)
        self.assertEqual([entry.work_type.value for entry in entries], ["meeting", "break", "meeting"])
        self.assertEqual(self.repository.get_for_day(self.runtime.user.id, self.now.date()).worked_hours(), 6)
        panel.content_input.setPlainText("Updated review")
        panel.save_button.click()
        self.assertEqual(self.repository.get_entry(self.runtime.user.id, entries[-1].id).note, "Updated review")
        self.assertEqual(len(self.repository.list_for_day(self.runtime.user.id, self.now.date())), 3)
        self.assertEqual(panel.work_type_combo.currentData(), "normal")
        panel.clock_in_button.click()
        self.assertEqual(panel.view_model.service.timer.work_type.value, "normal")
        self.warning.assert_not_called()

    def test_discard_timer_is_an_independent_confirmed_action(self):
        panel = self.panel
        panel.time_tabs.setCurrentIndex(1)
        panel.clock_in_button.click()
        self.assertTrue(panel.discard_timer_button.isEnabled())
        with patch("worklogger.presentation.widgets.time_entries.QMessageBox.question", return_value=QMessageBox.StandardButton.No):
            panel.discard_timer_button.click()
        self.assertIsNotNone(panel.view_model.service.timer)
        with patch("worklogger.presentation.widgets.time_entries.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            panel.discard_timer_button.click()
        self.assertIsNone(panel.view_model.service.timer)
        self.assertEqual(self.repository.list_for_day(self.runtime.user.id, self.now.date()), ())
        self.assertFalse(panel.discard_timer_button.isEnabled())
        self.assertTrue(panel.clock_in_button.isEnabled())

    def test_imported_event_actions_preserve_the_source_and_work_records(self):
        events = SQLiteCalendarEventRepository(self.runtime.connection_factory)
        event = CalendarEvent(None, self.runtime.user.id, self.now.date(), "Team discussion", "09:00", "10:00")
        events.add_many(self.runtime.user.id, (event,))
        self.window.refresh()
        card = next(button for button in self.window.calendar_page.records_widget.findChildren(QPushButton, "calendar_time_entry_button")
                    if button.property("entry_id") is None)
        card.click()
        self.assertEqual(self.panel.content_input.toPlainText(), "Team discussion")
        self.assertEqual(self.repository.list_for_day(self.runtime.user.id, self.now.date()), ())
        self.panel.save_button.click()
        original = events.list_for_day(self.runtime.user.id, self.now.date())[0]
        with self.assertRaises(ValueError):
            events.remove(self.runtime.user.id + 1, original)
        card = next(button for button in self.window.calendar_page.records_widget.findChildren(QPushButton, "calendar_time_entry_button")
                    if button.property("entry_id") is None)
        with patch("worklogger.presentation.widgets.time_entries.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            card.delete_button.click()
        self.assertEqual(events.list_for_day(self.runtime.user.id, self.now.date()), ())
        self.assertEqual(len(self.repository.list_for_day(self.runtime.user.id, self.now.date())), 1)
        self.warning.assert_not_called()
