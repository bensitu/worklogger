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
from PySide6.QtWidgets import QMessageBox
from PySide6.QtGui import QCloseEvent

from worklogger.bootstrap import DesktopRuntimeConfig, build_desktop_runtime
from worklogger.infrastructure.language_preferences import LanguagePreferences
from worklogger.infrastructure.repositories.worklog_sqlite import SQLiteWorkLogRepository
from worklogger.infrastructure.repositories.calendar_sqlite import SQLiteCalendarEventRepository
from worklogger.domain.calendar.models import CalendarEvent
from worklogger.presentation.shell.app_window import AppWindowConfig
from worklogger.presentation.job_runner import ImmediateJobRunner, QtJobRunner
from worklogger.app.use_cases.ai import RewriteTextResult
from worklogger.domain.shared.result import Result
from PySide6.QtCore import QTime


class TimeEntryWorkflowTests(unittest.TestCase):
    def test_tray_recording_uses_automatic_state_and_preserves_manual_input(self):
        from worklogger.presentation.shell.residency import QtResidencyController, ResidencyViewModel
        from worklogger.app.use_cases.settings import GetSettingHandler, SetSettingHandler
        from tests.presentation.test_settings_presentation import MemorySettingsRepository
        settings = MemorySettingsRepository()
        controller = QtResidencyController(ResidencyViewModel(user_id=1,
            get_handler=GetSettingHandler(settings), set_handler=SetSettingHandler(settings),
            platform="win32", availability_probe=lambda: True),
            application=self.runtime.application, tray_available=lambda: True)
        controller.attach(self.window)
        panel = self.panel
        controller.bind_recording(start_callback=panel.start_recording, end_callback=panel.end_recording,
                                  state_probe=panel.recording_action_state)
        panel.recording_changed.connect(controller.update_recording_actions)
        panel.view_model.auto_work_type = "meeting"
        panel.view_model.auto_content = "Timed meeting"
        panel.start_input.setText("07:00")
        panel.end_input.setText("08:00")
        panel.content_input.setPlainText("Unsaved manual description")
        draft = panel.view_model.draft
        self.window.hide()
        self.assertTrue(controller._start_action.isEnabled())
        self.assertFalse(controller._end_action.isEnabled())
        controller._start_action.trigger()
        self.assertFalse(controller._start_action.isEnabled())
        self.assertTrue(controller._end_action.isEnabled())
        self.assertEqual(panel.view_model.timer.work_type.value, "meeting")
        self.assertEqual(panel.view_model.draft, draft)
        panel.is_busy = True
        controller.update_recording_actions()
        self.assertFalse(controller._end_action.isEnabled())
        panel.is_busy = False
        controller.update_recording_actions()
        self.now += timedelta(hours=1)
        controller._end_action.trigger()
        self.assertTrue(controller._start_action.isEnabled())
        self.assertFalse(controller._end_action.isEnabled())
        entry = self.repository.list_for_day(self.runtime.user.id, self.now.date())[0]
        self.assertEqual((entry.note, entry.work_type.value, entry.worked_hours()), ("Timed meeting", "meeting", 1))
        self.assertEqual(panel.view_model.draft, draft)
        self.assertTrue(self.window.isHidden())
        panel.clear_button.click()
        self.warning.assert_not_called()

    def test_custom_type_management_and_manual_automatic_recording_preserve_saved_categories(self):
        from worklogger.presentation.widgets.work_type_manager import WorkTypeManagerDialog
        from worklogger.presentation.settings import SettingsWorkflowController
        from worklogger.presentation.viewmodels.work_types import WorkTypeManagerViewModel
        from tests.presentation.test_settings_presentation import _view_model, MemorySettingsRepository
        from tests.presentation.test_settings_workflow import FakeAuthViewModel, FakeDataManagementViewModel
        panel = self.panel
        controller = SettingsWorkflowController(settings_view_model=_view_model(MemorySettingsRepository()),
            auth_view_model=FakeAuthViewModel(), user=self.runtime.user,
            data_management_view_model=FakeDataManagementViewModel(),
            work_types_view_model=WorkTypeManagerViewModel(panel.view_model.service.work_types))
        settings = controller.create_page()
        self.addCleanup(settings.deleteLater)
        settings.work_types_changed.connect(panel.refresh_work_types)
        definitions = []

        def create_type(dialog):
            dialog.name_input.setText("Research")
            dialog.category_combo.setCurrentIndex(dialog.category_combo.findData("work"))
            dialog.save_button.click()
            definitions.append(dialog.type_list.currentItem().data(256))
            return 1

        with patch.object(WorkTypeManagerDialog, "exec", create_type):
            settings.manage_work_types_button.click()
        definition = definitions[0]
        panel.work_type_combo.setCurrentIndex(panel.work_type_combo.findData(definition.value))
        panel.start_input.setText("09:00")
        panel.end_input.setText("10:00")
        panel.save_button.click()
        first = self.repository.list_for_day(self.runtime.user.id, self.now.date())[0]
        self.assertEqual((first.work_type.label, first.worked_hours()), ("Research", 1))
        self.assertEqual(panel.work_type_combo.currentData(), "normal")
        panel.time_tabs.setCurrentIndex(1)
        self.now += timedelta(hours=1)
        panel.work_type_combo.setCurrentIndex(panel.work_type_combo.findData(definition.value))
        panel.clock_in_button.click()
        panel.content_input.setPlainText("Ongoing research")

        def edit_type(dialog):
            dialog.type_list.setCurrentRow(0)
            dialog.name_input.setText("Study")
            dialog.category_combo.setCurrentIndex(dialog.category_combo.findData("break"))
            dialog.save_button.click()
            return 1

        with patch.object(WorkTypeManagerDialog, "exec", edit_type):
            settings.manage_work_types_button.click()
        self.assertEqual(panel.work_type_combo.currentText(), "Research")
        self.assertEqual(panel.content_input.toPlainText(), "Ongoing research")
        self.assertEqual(panel.view_model.timer.work_type.category, "work")
        self.now += timedelta(hours=1)
        panel.clock_out_button.click()
        self.assertEqual(len(self.repository.list_for_day(self.runtime.user.id, self.now.date())), 2)
        panel.edit_entry(first)
        panel.content_input.setPlainText("Revised description")
        panel.save_button.click()
        self.assertEqual(self.repository.get_entry(self.runtime.user.id, first.id).work_type.label, "Research")
        self.assertEqual(sum(entry.worked_hours() for entry in self.repository.list_for_day(self.runtime.user.id, self.now.date())), 2)
        self.warning.assert_not_called()

    def setUp(self):
        from tests.presentation.qt_support import dispose_test_windows
        self.addCleanup(dispose_test_windows)
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

    def test_clock_selection_and_polishing_change_only_the_local_draft(self):
        panel = self.panel
        panel.start_input.setText("09:00")
        panel.end_input.setText("10:00")
        panel.work_type_combo.setCurrentIndex(panel.work_type_combo.findData("meeting"))
        panel.content_input.setPlainText("Draft description")
        from worklogger.presentation.widgets.time_picker import TimePickerDialog
        panel.start_input.actions()[0].trigger()
        picker = panel.findChild(TimePickerDialog)
        picker.time_input.setTime(QTime(9, 15))
        picker.select_button.click()
        commands = []
        class Rewriter:
            available = True
            def handle(self, command):
                commands.append(command)
                return Result.success(RewriteTextResult("Prepared agenda"))
        panel.view_model._rewrite_handler = Rewriter()
        panel.refresh_ai_availability()
        panel.polish_button.click()
        self.assertEqual(panel.content_input.toPlainText(), "Prepared agenda")
        self.assertEqual((panel.start_input.text(), panel.end_input.text(), panel.work_type_combo.currentData()), ("09:15", "10:00", "meeting"))
        self.assertEqual(commands[0].context, "time_entry")
        self.assertEqual(self.repository.list_for_day(self.runtime.user.id, self.now.date()), ())
        panel.clear_button.click()

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
        records = self.window.calendar_page.records_widget.entry_buttons
        self.assertEqual(len(records), 2)
        current = records[entries[0].id]
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
        card = self.window.calendar_page.records_widget.entry_buttons[saved.id]
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

    def test_automatic_recording_and_fixed_breaks_have_distinct_effects(self):
        panel = self.panel
        panel.time_tabs.setCurrentIndex(1)
        panel.work_type_combo.setCurrentIndex(panel.work_type_combo.findData("meeting"))
        panel.content_input.setPlainText("Planning")
        panel.clock_in_button.click()
        self.assertFalse(panel.break_button.isEnabled())
        panel.break_button.click()
        self.assertEqual(self.repository.list_for_day(self.runtime.user.id, self.now.date()), ())
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
        panel.clock_out_button.click()
        self.assertEqual(len(self.repository.list_for_day(self.runtime.user.id, self.now.date())), 1)
        self.assertTrue(panel.break_button.isEnabled())
        panel.break_button.click()
        entries = self.repository.list_for_day(self.runtime.user.id, self.now.date())
        self.assertEqual(len(entries), 2)
        self.assertEqual((entries[-1].work_type.value, entries[-1].start_time, entries[-1].end_time), ("break", "12:00", "13:00"))
        self.assertIsNone(panel.view_model.service.timer)
        self.assertEqual(panel.work_type_combo.currentData(), "normal")
        self.now += timedelta(hours=1)
        panel._tick()
        self.assertIsNone(panel.view_model.service.timer)
        panel.work_type_combo.setCurrentIndex(panel.work_type_combo.findData("meeting"))
        panel.clock_in_button.click()
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

    def test_break_shortcut_records_without_starting_a_timer(self):
        panel = self.panel
        panel.time_tabs.setCurrentIndex(1)
        self.assertTrue(panel.break_button.isEnabled())
        panel.content_input.setPlainText("Lunch")
        panel.break_button.click()
        entries = self.repository.list_for_day(self.runtime.user.id, self.now.date())
        self.assertEqual(len(entries), 1)
        self.assertEqual((entries[0].work_type.value, entries[0].start_time, entries[0].end_time), ("break", "09:00", "10:00"))
        self.assertIsNone(panel.view_model.service.timer)
        self.assertFalse(panel.clock_out_button.isEnabled())
        card = self.window.calendar_page.records_widget.entry_buttons[entries[0].id]
        self.assertIn("09:00 - 10:00", card.label.text())
        panel.content_input.setPlainText("Updated lunch")
        panel.save_button.click()
        self.assertEqual(self.repository.get_entry(self.runtime.user.id, entries[0].id).note, "Updated lunch")
        self.now += timedelta(minutes=1)
        original = self.repository.get_entry(self.runtime.user.id, entries[0].id)
        panel.content_input.setPlainText("Back to work")
        with patch("worklogger.presentation.widgets.time_entries.QMessageBox.exec", return_value=QMessageBox.StandardButton.No):
            panel.clock_in_button.click()
        self.assertIsNone(panel.view_model.service.timer)
        self.assertEqual(self.repository.get_entry(self.runtime.user.id, original.id), original)
        with patch("worklogger.presentation.widgets.time_entries.QMessageBox.exec", return_value=QMessageBox.StandardButton.Yes):
            panel.clock_in_button.click()
        self.assertEqual(panel.view_model.service.timer.started_at, self.now)
        self.assertEqual(panel.view_model.service.timer.content, "Back to work")
        shortened = self.repository.get_entry(self.runtime.user.id, original.id)
        self.assertEqual((shortened.start_time, shortened.end_time, shortened.note), ("09:00", "09:01", "Updated lunch"))
        self.assertFalse(panel.break_button.isEnabled())
        panel.view_model.default_break_hours = 0
        panel._update_actions()
        self.assertFalse(panel.break_button.isEnabled())
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
        card = next(iter(self.window.calendar_page.records_widget.event_buttons.values()))
        card.click()
        self.assertEqual(self.panel.content_input.toPlainText(), "Team discussion")
        self.assertEqual(self.repository.list_for_day(self.runtime.user.id, self.now.date()), ())
        self.panel.save_button.click()
        original = events.list_for_day(self.runtime.user.id, self.now.date())[0]
        with self.assertRaises(ValueError):
            events.remove(self.runtime.user.id + 1, original)
        card = next(iter(self.window.calendar_page.records_widget.event_buttons.values()))
        with patch("worklogger.presentation.widgets.time_entries.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            card.delete_button.click()
        self.assertEqual(events.list_for_day(self.runtime.user.id, self.now.date()), ())
        self.assertEqual(len(self.repository.list_for_day(self.runtime.user.id, self.now.date())), 1)
        self.warning.assert_not_called()
