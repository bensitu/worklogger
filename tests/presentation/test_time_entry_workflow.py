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
    def test_record_modes_share_content_classification_and_saved_identity(self):
        panel = self.panel
        panel.start_input.setText("09:00")
        panel.end_input.setText("10:00")
        panel.work_type_combo.setCurrentIndex(panel.work_type_combo.findData("meeting"))
        panel.content_input.setPlainText("Agenda")
        panel.save_button.click()
        saved = self.repository.list_for_day(self.runtime.user.id, self.now.date())[0]
        panel.time_tabs.setCurrentIndex(1)
        self.assertEqual(panel.content_input.toPlainText(), "Agenda")
        self.assertEqual(panel.work_type_combo.currentData(), "meeting")
        self.assertEqual(panel.view_model.auto_completed.id, saved.id)
        panel.work_type_combo.setCurrentIndex(panel.work_type_combo.findData("training"))
        panel.content_input.setPlainText("Training agenda")
        panel.save_button.click()
        edited = self.repository.get_entry(self.runtime.user.id, saved.id)
        self.assertEqual((edited.note, edited.work_type.value), ("Training agenda", "training"))
        panel.time_tabs.setCurrentIndex(0)
        self.assertEqual(panel.content_input.toPlainText(), edited.note)
        panel.start_input.setText("09:15")
        panel.time_tabs.setCurrentIndex(1)
        panel.content_input.setPlainText("Further detail")
        panel.save_button.click()
        self.assertEqual(self.repository.get_entry(self.runtime.user.id, saved.id).start_time, "09:00")
        panel.time_tabs.setCurrentIndex(0)
        self.assertEqual(panel.start_input.text(), "09:15")
        panel.save_button.click()
        self.assertEqual(self.repository.get_entry(self.runtime.user.id, saved.id).start_time, "09:15")
        self.assertEqual(len(self.repository.list_for_day(self.runtime.user.id, self.now.date())), 1)
        panel.clear_button.click()
        panel.time_tabs.setCurrentIndex(1)
        self.assertEqual(panel.content_input.toPlainText(), "")
        self.assertEqual(panel.work_type_combo.currentData(), "normal")
        self.assertIsNone(panel.view_model.auto_completed)

    def test_active_timer_content_is_shared_without_editable_manual_boundaries(self):
        panel = self.panel
        panel.content_input.setPlainText("Initial description")
        panel.time_tabs.setCurrentIndex(1)
        panel.clock_in_button.click()
        panel.content_input.setPlainText("Active description")
        panel.time_tabs.setCurrentIndex(0)
        self.assertEqual(panel.content_input.toPlainText(), "Active description")
        self.assertFalse(panel.start_input.isEnabled())
        self.assertFalse(panel.work_type_combo.isEnabled())
        panel.content_input.setPlainText("Revised description")
        panel.save_button.click()
        self.assertEqual(panel.view_model.timer.content, "Revised description")
        panel.time_tabs.setCurrentIndex(1)
        self.assertEqual(panel.content_input.toPlainText(), "Revised description")
        self.now += timedelta(hours=1)
        panel.clock_out_button.click()
        panel.time_tabs.setCurrentIndex(0)
        self.assertEqual(panel.content_input.toPlainText(), "Revised description")
        self.assertEqual(panel.view_model.draft.original.note, "Revised description")
        self.assertTrue(panel.start_input.isEnabled())
        self.assertEqual(len(self.repository.list_for_day(self.runtime.user.id, self.now.date())), 1)
        self.warning.assert_not_called()

    def test_polishing_keeps_event_loop_and_calendar_available_and_rejects_late_results(self):
        from PySide6.QtCore import QTimer
        entered, release = threading.Event(), threading.Event()
        availability_reads = []
        class Rewriter:
            @property
            def available(self):
                availability_reads.append(True)
                return True
            def handle(self, command):
                entered.set()
                release.wait(3)
                return Result.success(RewriteTextResult("Processed text"))
        panel = self.panel
        runner = QtJobRunner()
        self.addCleanup(lambda: runner.shutdown(wait=True))
        self.addCleanup(release.set)
        panel._polish_task._runner = runner
        panel.view_model._rewrite_handler = Rewriter()
        self.window.show()
        panel.content_input.setPlainText("Original content")
        panel.refresh_ai_availability()
        count = len(availability_reads)
        panel.content_input.setPlainText("Original content")
        self.assertEqual(len(availability_reads), count)
        panel.polish_button.click()
        self.assertTrue(entered.wait(3))
        self.assertTrue(panel.processing_progress.isVisible())
        self.assertTrue(panel.content_input.isReadOnly())
        self.assertFalse(panel.is_busy)
        self.assertTrue(self.window.calendar_page.records_widget.isEnabled())
        ticks = []
        QTimer.singleShot(0, lambda: ticks.append(True))
        self.runtime.application.processEvents()
        self.assertEqual(ticks, [True])
        panel.time_tabs.setCurrentIndex(1)
        self.assertTrue(panel._polish_task.is_running)
        self.assertEqual(panel.content_input.toPlainText(), "Original content")
        panel.processing_progress.cancel_button.click()
        self.assertFalse(panel.content_input.isReadOnly())
        panel.content_input.setPlainText("New input")
        release.set()
        runner.shutdown(wait=True)
        self.runtime.application.processEvents()
        self.assertEqual(panel.content_input.toPlainText(), "New input")
        self.assertEqual(self.repository.list_for_day(self.runtime.user.id, self.now.date()), ())
        self.warning.assert_not_called()

    def test_settings_data_directory_uses_the_active_database_location(self):
        page = self.window.settings_page
        directory = Path(self.runtime.database_path).resolve().parent
        self.assertEqual(page.data_directory_input.text(), str(directory))
        self.assertTrue(page.data_directory_input.isReadOnly())
        self.assertTrue(page.open_data_directory_button.isEnabled())
        with patch("worklogger.presentation.settings.controller.QDesktopServices.openUrl", return_value=True) as opened:
            page.open_data_directory_button.click()
        self.assertEqual(Path(opened.call_args.args[0].toLocalFile()).resolve(), directory)

    def test_multi_record_assignment_and_recent_selection_preserve_editor_content(self):
        from worklogger.presentation.widgets.record_search import RecordSearchDialog
        from worklogger.presentation.widgets.batch_context import BatchContextDialog
        service = self.panel.view_model.service
        project = service.projects.save_project("Research").value
        item = service.projects.save_work_item(project.id, "Review").value
        for start, end in (("09:00", "10:00"), ("10:00", "11:00")):
            service.save_manual(self.now.date(), start, end, "normal", "Original")
        self.panel.content_input.setPlainText("Unsaved editor content")
        dialog = RecordSearchDialog(self.panel.view_model, self.now.date(), self.window, job_runner=ImmediateJobRunner())
        self.addCleanup(dialog.deleteLater)
        dialog.records_changed.connect(self.window._records_associated)
        for index in range(dialog.results.topLevelItemCount()):
            dialog.results.topLevelItem(index).setSelected(True)
        self.assertFalse(dialog.open_button.isEnabled())
        self.assertTrue(dialog.associate_button.isEnabled())
        dialog.associate_button.click()
        batch = dialog.findChild(BatchContextDialog)
        batch.picker.project_combo.setCurrentIndex(batch.picker.project_combo.findData(project.id))
        batch.picker.work_item_combo.setCurrentIndex(batch.picker.work_item_combo.findData(item.id))
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            batch.apply_button.click()
        records = self.repository.list_for_day(self.runtime.user.id, self.now.date())
        self.assertTrue(all(record.context.label == "Research / Review" for record in records))
        self.assertEqual(self.panel.content_input.toPlainText(), "Unsaved editor content")
        picker = self.panel.context_picker
        self.assertTrue(picker.recent_button.isEnabled())
        picker.recent_menu.actions()[0].trigger()
        self.assertEqual(picker.context().work_item_id, item.id)
        self.assertEqual(self.panel.content_input.toPlainText(), "Unsaved editor content")
        dialog.close()

    def test_timer_end_correction_handles_ambiguous_and_nonexistent_local_times(self):
        from zoneinfo import ZoneInfo
        from worklogger.presentation.widgets.end_timer import EndTimerDialog
        from worklogger.domain.worklog.rules import timestamp_span_hours
        zone = ZoneInfo("America/New_York")
        start = datetime(2026, 11, 1, 0, 30, tzinfo=zone)
        dialog = EndTimerDialog(start, start + timedelta(hours=5), zone)
        self.addCleanup(dialog.deleteLater)
        dialog.end_input.setDateTime(datetime(2026, 11, 1, 1, 30))
        self.assertEqual(dialog.offset_combo.count(), 2)
        dialog.offset_combo.setCurrentIndex(0)
        self.assertEqual(timestamp_span_hours(start, dialog.chosen_end()), 1)
        dialog.offset_combo.setCurrentIndex(1)
        self.assertEqual(timestamp_span_hours(start, dialog.chosen_end()), 2)
        gap_start = datetime(2026, 3, 8, 0, 30, tzinfo=zone)
        gap = EndTimerDialog(gap_start, gap_start + timedelta(hours=4), zone)
        self.addCleanup(gap.deleteLater)
        gap.end_input.setDateTime(datetime(2026, 3, 8, 2, 30))
        self.assertIsNone(gap.chosen_end())
        self.assertFalse(gap.end_button.isEnabled())

    def test_timer_reminders_are_nonblocking_and_long_timer_finish_requires_explicit_correction(self):
        from worklogger.presentation.widgets.end_timer import EndTimerDialog
        panel = self.panel
        panel.time_tabs.setCurrentIndex(1)
        panel.clock_in_button.click()
        notifications = []
        panel.reminder.connect(notifications.append)
        panel.view_model.set_timer_reminders(1, 0.5)
        self.now += timedelta(hours=2)
        panel._tick()
        self.runtime.application.processEvents()
        self.assertEqual(len(notifications), 2)
        panel._tick()
        self.runtime.application.processEvents()
        self.assertEqual(len(notifications), 2)
        self.assertEqual(self.repository.list_for_day(self.runtime.user.id, self.now.date()), ())
        started = panel.view_model.timer.started_at
        self.now = started + timedelta(hours=20)
        panel.clock_out_button.click()
        dialog = panel.findChild(EndTimerDialog)
        self.assertIsNotNone(dialog)
        self.assertIsNotNone(panel.view_model.timer)
        self.assertEqual(self.repository.list_for_day(self.runtime.user.id, started.date()), ())
        corrected = started + timedelta(hours=8)
        dialog.end_input.setDateTime(corrected.replace(tzinfo=None))
        dialog.end_button.click()
        saved = self.repository.list_for_day(self.runtime.user.id, started.date())[0]
        self.assertAlmostEqual(saved.worked_hours(), 8)
        self.assertIsNone(panel.view_model.timer)
        self.warning.assert_not_called()

    def test_record_actions_and_global_undo_work_after_the_last_record_is_deleted(self):
        panel = self.panel
        original = panel.view_model.service.save_manual(self.now.date(), "09:00", "12:00", "normal", "Work").value
        self.window.refresh()
        self.assertTrue(panel.undo_button.isEnabled())
        with patch("worklogger.presentation.widgets.time_entries.QInputDialog.getInt", return_value=(60, True)), \
                patch("worklogger.presentation.widgets.time_entries.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            panel._split_record(original)
        records = self.repository.list_for_day(self.runtime.user.id, self.now.date())
        self.assertEqual(len(records), 2)
        self.assertEqual(sum(record.worked_hours() for record in records), 3)
        with patch("worklogger.presentation.widgets.time_entries.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            panel._merge_record(*records)
            panel.undo_button.click()
        self.assertEqual(len(self.repository.list_for_day(self.runtime.user.id, self.now.date())), 2)
        with patch("worklogger.presentation.widgets.time_entries.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            panel.undo_button.click()
        restored = self.repository.list_for_day(self.runtime.user.id, self.now.date())[0]
        self.assertEqual(restored.id, original.id)
        with patch("worklogger.presentation.widgets.time_entries.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            panel.delete_entry(restored)
        self.assertEqual(self.repository.list_for_day(self.runtime.user.id, self.now.date()), ())
        self.assertTrue(panel.undo_button.isEnabled())
        with patch("worklogger.presentation.widgets.time_entries.QMessageBox.question", return_value=QMessageBox.StandardButton.No):
            panel.undo_button.click()
        self.assertEqual(self.repository.list_for_day(self.runtime.user.id, self.now.date()), ())
        with patch("worklogger.presentation.widgets.time_entries.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            panel.undo_button.click()
        self.assertEqual(self.repository.list_for_day(self.runtime.user.id, self.now.date())[0].id, original.id)
        self.warning.assert_not_called()

    def test_record_search_filters_preserve_focus_and_open_the_owned_entry(self):
        from worklogger.presentation.widgets.record_search import RecordSearchDialog
        first = self.panel.view_model.service.save_manual(self.now.date(), "09:00", "10:00", "meeting", "Planning").value
        self.panel.view_model.service.save_manual(self.now.date(), "10:00", "11:00", "normal", "Review")
        selected = []
        dialog = RecordSearchDialog(self.panel.view_model, self.now.date(), self.window, job_runner=ImmediateJobRunner())
        self.addCleanup(dialog.deleteLater)
        dialog.entry_selected.connect(selected.append)
        dialog.show()
        self.runtime.application.processEvents()
        self.assertEqual(dialog.results.topLevelItemCount(), 2)
        dialog.search_input.setFocus()
        dialog.search_input.setText("Plan")
        dialog._reload()
        self.assertEqual(dialog.results.topLevelItemCount(), 1)
        self.assertTrue(dialog.search_input.hasFocus())
        dialog.results.setCurrentItem(dialog.results.topLevelItem(0))
        dialog.open_button.click()
        self.assertEqual(selected, [first])
        self.assertTrue(self.window._switch_route("analytics"))
        self.assertTrue(self.window._open_found_entry(first))
        self.assertIs(self.window.page_stack.currentWidget(), self.window.calendar_page)
        self.assertEqual(self.panel.view_model.draft.original.id, first.id)
        self.warning.assert_not_called()

    def test_project_management_and_record_selection_share_persisted_context(self):
        from worklogger.presentation.widgets.project_manager import ProjectManagerDialog
        from worklogger.presentation.viewmodels.projects import ProjectManagerViewModel
        panel = self.panel
        service = panel.view_model.service.projects
        dialog = ProjectManagerDialog(ProjectManagerViewModel(service), self.window, job_runner=ImmediateJobRunner())
        self.addCleanup(dialog.deleteLater)
        dialog.changed.connect(panel.refresh_projects)
        dialog.project_name_input.setText("Research")
        dialog.project_code_input.setText("R1")
        dialog.project_save_button.click()
        project = service.list_projects().value[0]
        dialog.editor_tabs.setCurrentIndex(1)
        dialog.work_item_title_input.setText("Review")
        dialog.work_item_url_input.setText("https://example.test/issue/1")
        dialog.work_item_save_button.click()
        item = service.list_work_items(project.id).value[0]
        picker = panel.context_picker
        picker.project_combo.setCurrentIndex(picker.project_combo.findData(project.id))
        picker.work_item_combo.setCurrentIndex(picker.work_item_combo.findData(item.id))
        panel.start_input.setText("09:00")
        panel.end_input.setText("10:00")
        panel.content_input.setPlainText("Completed review")
        panel.save_button.click()
        record = self.repository.list_for_day(self.runtime.user.id, self.now.date())[0]
        self.assertEqual(record.context.label, "Research / Review")
        self.assertIn(record.context.label, self.window.calendar_page.records_widget.entry_buttons[record.id].label.text())
        panel.edit_entry(record)
        self.assertEqual(picker.work_item_combo.currentData(), item.id)
        panel.clear_button.click()
        panel.time_tabs.setCurrentIndex(1)
        picker.project_combo.setCurrentIndex(picker.project_combo.findData(project.id))
        picker.work_item_combo.setCurrentIndex(picker.work_item_combo.findData(item.id))
        self.now += timedelta(hours=1)
        panel.clock_in_button.click()
        self.assertFalse(picker.isEnabled())
        self.now += timedelta(hours=1)
        panel.clock_out_button.click()
        self.assertTrue(picker.isEnabled())
        timed = self.repository.list_for_day(self.runtime.user.id, self.now.date())[-1]
        self.assertEqual(timed.context, record.context)
        self.assertEqual(panel.work_type_combo.currentData(), "normal")
        dialog.work_item_title_input.setText("Unsaved rename")
        with patch("worklogger.presentation.widgets.project_manager.QMessageBox.question", return_value=QMessageBox.StandardButton.No):
            dialog.editor_tabs.setCurrentIndex(0)
            self.assertEqual(dialog.editor_tabs.currentIndex(), 1)
            self.assertEqual(dialog.work_item_title_input.text(), "Unsaved rename")
        with patch("worklogger.presentation.widgets.project_manager.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            dialog.editor_tabs.setCurrentIndex(0)
            dialog.project_archive_button.click()
        panel.edit_entry(record)
        self.assertEqual(picker.context().project_id, project.id)
        panel.content_input.setPlainText("Corrected description")
        panel.save_button.click()
        self.assertEqual(self.repository.get_entry(self.runtime.user.id, record.id).context, record.context)
        self.warning.assert_not_called()

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
        self.assertTrue(self.window.select_day(self.now.date() - timedelta(days=1)))
        panel.start_input.setText("07:00")
        panel.end_input.setText("08:00")
        panel.content_input.setPlainText("Unsaved manual description")
        panel.view_model.auto_work_type = "meeting"
        panel.view_model.auto_content = "Timed meeting"
        draft = panel.view_model.draft
        self.window.hide()
        self.assertTrue(controller._start_action.isEnabled())
        self.assertFalse(controller._end_action.isEnabled())
        controller._start_action.trigger()
        self.assertFalse(controller._start_action.isEnabled())
        self.assertTrue(controller._end_action.isEnabled())
        self.assertEqual(panel.view_model.timer.work_type.value, "meeting")
        self.assertEqual(panel.view_model.draft, draft)
        panel.time_tabs.setCurrentIndex(1)
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
        self.assertEqual(panel.work_type_combo.currentData(), definition.value)
        self.assertTrue(panel.new_record())
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
        self.panel._polish_task._runner = self.panel._job_runner
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
            self.assertTrue(panel.new_record())
            panel.start_input.setText(start)
            panel.end_input.setText(end)
            panel.work_type_combo.setCurrentIndex(panel.work_type_combo.findData(kind))
            panel.content_input.setPlainText(content)
            panel.save_button.click()
            self.assertEqual(panel.work_type_combo.currentData(), kind)
            self.assertEqual(panel.start_input.text(), start)
            self.assertEqual(panel.content_input.toPlainText(), content)
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
        self.assertEqual(panel.work_type_combo.currentData(), "meeting")
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
        self.assertEqual(panel.work_type_combo.currentData(), "break")
        panel.clear_button.click()
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
        self.assertEqual(panel.work_type_combo.currentData(), "meeting")
        entries = self.repository.list_for_day(self.runtime.user.id, self.now.date())
        self.assertEqual(len(entries), 3)
        self.assertEqual([entry.work_type.value for entry in entries], ["meeting", "break", "meeting"])
        self.assertEqual(self.repository.get_for_day(self.runtime.user.id, self.now.date()).worked_hours(), 6)
        panel.content_input.setPlainText("Updated review")
        panel.save_button.click()
        self.assertEqual(self.repository.get_entry(self.runtime.user.id, entries[-1].id).note, "Updated review")
        self.assertEqual(len(self.repository.list_for_day(self.runtime.user.id, self.now.date())), 3)
        self.assertEqual(panel.work_type_combo.currentData(), "meeting")
        panel.clear_button.click()
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
