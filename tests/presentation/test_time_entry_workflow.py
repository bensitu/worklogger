from datetime import date, datetime, timedelta
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QCloseEvent

from worklogger.bootstrap import DesktopRuntimeConfig, build_desktop_runtime
from worklogger.infrastructure.language_preferences import LanguagePreferences
from worklogger.infrastructure.repositories.worklog_sqlite import SQLiteWorkLogRepository
from worklogger.infrastructure.repositories.calendar_sqlite import SQLiteCalendarEventRepository
from worklogger.domain.calendar.models import CalendarEvent
from worklogger.domain.worklog.models import WorkMode
from worklogger.presentation.shell.app_window import AppWindowConfig
from worklogger.presentation.job_runner import ImmediateJobRunner, QtJobRunner
from worklogger.app.use_cases.ai import RewriteTextResult
from worklogger.domain.shared.result import Result
from PySide6.QtCore import QTime


def apply_boundary(dialog, wall):
    dialog.date_combo.setCurrentIndex(dialog.date_combo.findData(wall.date().isoformat()))
    dialog.time_input.setText(wall.strftime("%H:%M"))
    dialog.apply_time_button.click()


def editor_state(panel):
    return panel.view_model.editor_state(automatic=panel.time_tabs.currentIndex() == 1)


def open_classification(panel):
    panel.window().show()
    QApplication.processEvents()
    panel.classification_button.click()
    popup = panel._classification_popup
    assert popup is not None and popup.isVisible()
    return popup


def apply_classification(panel, entry_type):
    popup = open_classification(panel)
    combo = popup.period_type_combo
    if combo.findData(entry_type) < 0:
        combo = popup.leave_type_combo
        popup.section_tabs.setCurrentIndex(1)
    assert combo.findData(entry_type) >= 0
    combo.setCurrentIndex(combo.findData(entry_type))
    popup.apply_button.click()
    assert not popup.isVisible(), popup.error_label.text()
    return popup


class TimeEntryWorkflowTests(unittest.TestCase):
    def test_classification_stages_all_fields_and_applies_one_validated_draft_update(self):
        from worklogger.domain.projects.models import WorkContext

        panel = self.panel
        projects = panel.view_model.service.projects
        project = projects.save_project("Platform").value
        item = projects.save_work_item(project.id, "Authentication").value
        panel.refresh_projects()
        record = panel.view_model.service.save_manual(self.now.date(), "09:00", "10:00", "normal", "Planning").value
        panel.edit_entry(record)
        before = panel.view_model.draft
        dirty = []
        panel.dirty_changed.connect(dirty.append)
        with patch.object(panel.view_model, "validate_selection", wraps=panel.view_model.validate_selection) as validate:
            popup = open_classification(panel)
            popup.period_type_combo.setCurrentIndex(popup.period_type_combo.findData("meeting"))
            popup.work_mode_combo.setCurrentIndex(popup.work_mode_combo.findData(WorkMode.REMOTE))
            popup.context_picker.project_combo.setCurrentIndex(popup.context_picker.project_combo.findData(project.id))
            popup.context_picker.work_item_combo.setCurrentIndex(popup.context_picker.work_item_combo.findData(item.id))
            popup.period_type_combo.setCurrentIndex(popup.period_type_combo.findData("break"))
            self.assertTrue(popup.work_metadata.isHidden())
            popup.section_tabs.setCurrentIndex(1)
            popup.section_tabs.setCurrentIndex(0)
            popup.period_type_combo.setCurrentIndex(popup.period_type_combo.findData("meeting"))
            self.assertEqual(popup.work_mode_combo.currentData(), WorkMode.REMOTE)
            self.assertEqual(popup.context_picker.context().work_item_id, item.id)
            self.assertEqual(panel.view_model.draft, before)
            self.assertFalse(panel.is_dirty)
            validate.assert_not_called()
            dirty.clear()
            with patch.object(panel.view_model, "update", wraps=panel.view_model.update) as update:
                popup.apply_button.click()
                update.assert_called_once()
            validate.assert_called_once()
        self.assertFalse(popup.isVisible())
        self.assertEqual(dirty, [True])
        state = editor_state(panel)
        self.assertEqual((state.entry_type, state.work_mode, state.context),
                         ("meeting", WorkMode.REMOTE, WorkContext(project.id, item.id, "Platform", "Authentication")))
        self.assertEqual(self.repository.list_for_day(self.runtime.user.id, self.now.date()), (record,))
        self.assertIn("Meeting", panel.classification_button.accessibleDescription())
        self.assertIn("Platform / Authentication", panel.classification_button.accessibleDescription())

    def test_classification_cancel_keyboard_and_outside_click_preserve_the_draft(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtTest import QTest

        panel = self.panel
        baseline = panel.view_model.draft
        for dismissal in ("cancel", "escape", "outside"):
            with self.subTest(dismissal=dismissal):
                popup = open_classification(panel)
                popup.period_type_combo.setCurrentIndex(popup.period_type_combo.findData("meeting"))
                popup.work_mode_combo.setCurrentIndex(popup.work_mode_combo.findData(WorkMode.REMOTE))
                if dismissal == "cancel":
                    popup.cancel_button.click()
                elif dismissal == "escape":
                    QTest.keyClick(popup.period_type_combo, Qt.Key.Key_Escape)
                else:
                    QTest.mouseClick(self.window.windowHandle(), Qt.MouseButton.LeftButton,
                                     Qt.KeyboardModifier.NoModifier, QPoint(10, 10))
                QApplication.processEvents()
                self.assertFalse(popup.isVisible())
                self.assertEqual(panel.view_model.draft, baseline)
                self.assertFalse(panel.is_dirty)
                popup.apply_button.click()
                self.assertEqual(panel.view_model.draft, baseline)
        popup = open_classification(panel)
        popup.period_type_combo.setCurrentIndex(popup.period_type_combo.findData("training"))
        for _ in range(12):
            if QApplication.focusWidget() is popup.apply_button:
                break
            QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Tab)
        self.assertIs(QApplication.focusWidget(), popup.apply_button)
        QTest.keyClick(popup.apply_button, Qt.Key.Key_Return)
        self.assertFalse(popup.isVisible())
        self.assertEqual(editor_state(panel).entry_type, "training")

    def test_classification_popup_invalidates_on_editor_and_operation_changes(self):
        from worklogger.domain.shared.errors import InfrastructureError

        panel = self.panel
        for change in (
            lambda: panel.load_day(self.now.date() + timedelta(days=1)),
            lambda: panel.time_tabs.setCurrentIndex(1 - panel.time_tabs.currentIndex()),
            lambda: panel.content_input.setPlainText(panel.content_input.toPlainText() + "Changed"),
            panel.refresh_entry_types,
            panel.refresh_projects,
            lambda: panel._submit(lambda model: Result.failure(InfrastructureError("worklog_save_failed", "worklog_save_failed"))),
            panel.hide,
        ):
            popup = open_classification(panel)
            popup.period_type_combo.setCurrentIndex(popup.period_type_combo.findData("meeting"))
            change()
            self.assertFalse(popup.isVisible())
            current = panel.view_model.draft
            popup.apply_button.click()
            self.assertEqual(panel.view_model.draft, current)
            self.assertEqual(editor_state(panel).entry_type, "normal")
            panel.show()

    def test_manual_break_and_leave_clear_work_metadata_only_on_apply(self):
        panel = self.panel
        project = panel.view_model.service.projects.save_project("Platform").value
        panel.refresh_projects()
        for index, kind in enumerate(("break", "sick_leave")):
            with self.subTest(entry_type=kind):
                panel.new_record()
                popup = open_classification(panel)
                popup.work_mode_combo.setCurrentIndex(popup.work_mode_combo.findData(WorkMode.REMOTE))
                popup.context_picker.project_combo.setCurrentIndex(popup.context_picker.project_combo.findData(project.id))
                popup.apply_button.click()
                self.assertEqual(editor_state(panel).work_mode, WorkMode.REMOTE)
                panel.start_input.setText(f"{9 + index:02d}:00")
                panel.end_input.setText(f"{10 + index:02d}:00")
                apply_classification(panel, kind)
                self.assertIsNone(editor_state(panel).work_mode)
                self.assertFalse(editor_state(panel).context.project_id)
                panel.save_button.click()
                saved = self.repository.list_for_day(self.runtime.user.id, self.now.date())[-1]
                self.assertEqual(saved.entry_type.value, kind)
                self.assertEqual(saved.worked_hours(), 0)
                self.assertIsNone(saved.work_mode)
                self.assertIsNone(saved.context.project_id)
        self.assertEqual(len(self.repository.list_for_day(self.runtime.user.id, self.now.date())), 2)
        self.warning.assert_not_called()

    def test_automatic_classification_disables_nonwork_and_locks_during_timer(self):
        panel = self.panel
        panel.time_tabs.setCurrentIndex(1)
        popup = open_classification(panel)
        self.assertFalse(popup.section_tabs.isTabEnabled(1))
        index = popup.period_type_combo.findData("break")
        self.assertGreaterEqual(index, 0)
        self.assertFalse(popup.period_type_combo.model().item(index).isEnabled())
        self.assertTrue(popup.auto_help_label.isVisible())
        popup.work_mode_combo.setCurrentIndex(popup.work_mode_combo.findData(WorkMode.BUSINESS_TRIP))
        popup.apply_button.click()
        panel.clock_in_button.click()
        self.assertEqual(panel.view_model.timer.work_mode, WorkMode.BUSINESS_TRIP)
        self.assertFalse(panel.classification_button.isEnabled())
        popup.apply_button.click()
        self.assertEqual(panel.view_model.timer.work_mode, WorkMode.BUSINESS_TRIP)
        self.now += timedelta(hours=1)
        panel.clock_out_button.click()
        self.assertTrue(panel.classification_button.isEnabled())
        self.assertEqual(editor_state(panel).work_mode, WorkMode.BUSINESS_TRIP)

    def test_historical_untimed_leave_keeps_empty_clock_boundaries_after_classification_edit(self):
        from worklogger.domain.worklog.models import EntryType

        panel = self.panel
        with self.runtime.connection_factory.transaction(write=True) as connection:
            cursor = connection.execute("INSERT INTO worklog(user_id,d,entry_type,note) VALUES(?,?,?,?)",
                (self.runtime.user.id, self.now.date().isoformat(), "paid_leave", "Historical leave"))
            record_id = cursor.lastrowid
        record = self.repository.get_entry(self.runtime.user.id, record_id)
        panel.edit_entry(record)
        apply_classification(panel, "sick_leave")
        self.assertEqual((panel.start_input.text(), panel.end_input.text()), ("", ""))
        panel.save_button.click()
        saved = self.repository.get_entry(self.runtime.user.id, record.id)
        self.assertEqual(saved.entry_type, EntryType.SICK_LEAVE)
        self.assertFalse(saved.has_times)
        self.assertEqual(saved.leave_hours(), record.leave_hours())
        self.warning.assert_not_called()

    def test_classification_rejects_stale_custom_catalog_but_preserves_historical_snapshots(self):
        panel = self.panel
        catalog = panel.view_model.service.entry_types
        definition = catalog.save("Research", "work").value
        definition = catalog.save("Study", "work", definition).value
        panel.refresh_entry_types()
        apply_classification(panel, definition.value)
        panel.start_input.setText("09:00")
        panel.end_input.setText("10:00")
        panel.save_button.click()
        original = panel.view_model.draft.original
        panel.new_record()
        before = panel.view_model.draft
        popup = open_classification(panel)
        popup.period_type_combo.setCurrentIndex(popup.period_type_combo.findData(definition.value))
        changed = catalog.save("Rest", "break", definition).value
        popup.apply_button.click()
        self.assertTrue(popup.isVisible())
        self.assertTrue(popup.error_label.isVisible())
        self.assertEqual(panel.view_model.draft, before)
        self.assertFalse(panel.is_dirty)
        popup.cancel_button.click()
        panel.refresh_entry_types()
        panel.edit_entry(original)
        popup = open_classification(panel)
        self.assertEqual(popup.period_type_combo.currentText(), "Study")
        self.assertFalse(popup.work_metadata.isHidden())
        popup.apply_button.click()
        self.assertFalse(popup.isVisible())
        self.assertFalse(panel.is_dirty)
        panel.new_record()
        popup = open_classification(panel)
        popup.period_type_combo.setCurrentIndex(popup.period_type_combo.findData(changed.value))
        catalog.archive(changed)
        popup.apply_button.click()
        self.assertTrue(popup.isVisible())
        self.assertTrue(popup.error_label.isVisible())
        self.assertFalse(panel.is_dirty)

    def test_classification_validates_archived_projects_and_refreshes_new_context_labels(self):
        panel = self.panel
        projects = panel.view_model.service.projects
        project = projects.save_project("Platform").value
        panel.refresh_projects()
        popup = open_classification(panel)
        popup.context_picker.project_combo.setCurrentIndex(popup.context_picker.project_combo.findData(project.id))
        renamed = projects.save_project("Payments", previous=project).value
        popup.apply_button.click()
        self.assertFalse(popup.isVisible())
        self.assertEqual(editor_state(panel).context.project_label, "Payments")
        panel.new_record()
        popup = open_classification(panel)
        popup.context_picker.project_combo.setCurrentIndex(popup.context_picker.project_combo.findData(project.id))
        projects.archive_project(renamed)
        popup.apply_button.click()
        self.assertTrue(popup.isVisible())
        self.assertTrue(popup.error_label.isVisible())
        self.assertFalse(panel.is_dirty)

    def test_legacy_classification_is_preserved_for_editing_but_cannot_start_an_idle_timer(self):
        from worklogger.domain.worklog.models import EntryType, WorkLog

        panel = self.panel
        record = self.repository.save_entry(WorkLog(self.runtime.user.id, self.now.date(), "09:00", "10:00",
                                                   entry_type=EntryType.REMOTE, work_mode=WorkMode.REMOTE))
        panel.edit_entry(record)
        popup = open_classification(panel)
        self.assertEqual(popup.period_type_combo.currentData(), "remote")
        self.assertTrue(popup.legacy_label.isVisible())
        popup.apply_button.click()
        self.assertFalse(panel.is_dirty)
        panel.time_tabs.setCurrentIndex(1)
        self.assertFalse(panel.clock_in_button.isEnabled())
        self.assertFalse(panel.recording_action_state()[0])
        popup = open_classification(panel)
        popup.apply_button.click()
        self.assertFalse(popup.isVisible())
        panel.content_input.setPlainText("Historic description")
        panel.save_button.click()
        self.assertEqual(self.repository.get_entry(self.runtime.user.id, record.id).entry_type, EntryType.REMOTE)
        apply_classification(panel, "meeting")
        self.assertTrue(panel.clock_in_button.isEnabled())

    def test_project_menu_distinguishes_all_records_from_unlinked_records_and_preserves_fixed_filters(self):
        from worklogger.domain.projects.models import WorkContext
        from worklogger.domain.worklog.models import WorkLog
        from worklogger.domain.worklog.search import EntryFilter
        from worklogger.infrastructure.i18n import _
        from worklogger.presentation.widgets.record_search import RecordSearchDialog

        service, day = self.panel.view_model.service, self.now.date()
        project = service.projects.save_project("Research").value
        item = service.projects.save_work_item(project.id, "Review").value
        service.save_manual(day, "09:00", "10:00", "normal", "Linked", context=WorkContext(project.id, item.id))
        service.save_manual(day, "10:00", "11:00", "normal", "Plain")
        self.repository.save_entry(WorkLog(self.runtime.user.id, day, "11:00", "12:00", note="Imported",
                                          context=WorkContext(project_label="Previous", work_item_label="Task")))
        dialog = RecordSearchDialog(self.panel.view_model, day, self.window, job_runner=ImmediateJobRunner())
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.results.topLevelItemCount(), 3)
        self.assertFalse(dialog.item_combo.isEnabled())
        dialog.project_combo.setCurrentIndex(dialog.project_combo.findData(project.id))
        self.assertTrue(dialog.item_combo.isEnabled())
        dialog.item_combo.setCurrentIndex(dialog.item_combo.findData(item.id))
        dialog._reload()
        self.assertEqual(dialog.results.topLevelItemCount(), 1)
        dialog.project_combo.setCurrentIndex(dialog.project_combo.findText(_("No linked project")))
        self.assertTrue(dialog.project_combo.isEnabled())
        self.assertFalse(dialog.item_combo.isEnabled())
        self.assertIsNone(dialog._criteria().project_id)
        self.assertIsNone(dialog._criteria().work_item_id)
        self.assertTrue(dialog._criteria().unclassified)
        dialog._reload()
        self.assertEqual(dialog.results.topLevelItemCount(), 2)
        dialog.project_combo.setCurrentIndex(0)
        dialog._reload()
        self.assertFalse(dialog._criteria().unclassified)
        self.assertEqual(dialog.results.topLevelItemCount(), 3)
        dialog.reject()
        criteria = EntryFilter(day, day, unclassified=True, project_label="Previous", work_item_label="Task")
        fixed = RecordSearchDialog(self.panel.view_model, day, self.window,
                                   job_runner=ImmediateJobRunner(), criteria=criteria)
        self.addCleanup(fixed.deleteLater)
        self.assertFalse(fixed.project_combo.isEnabled())
        self.assertFalse(fixed.item_combo.isEnabled())
        self.assertEqual(fixed._criteria(), criteria)
        self.assertEqual(fixed.results.topLevelItemCount(), 1)
        fixed.reject()

    def test_record_search_uses_the_visible_month_and_shared_date_ranges(self):
        from worklogger.presentation.widgets.date_range import DateRangeControls

        self.window.next_month()
        month = self.window.current_month
        self.window.open_record_search()
        dialog = self.window._record_search_dialog
        self.assertIsInstance(dialog.date_range, DateRangeControls)
        self.assertEqual(dialog._criteria().start, month)
        self.assertEqual(dialog._criteria().end.month, month.month)
        self.assertGreater(dialog._criteria().end.day, 27)
        for mode, start, end in (("year", date(month.year, 1, 1), date(month.year, 12, 31)),
                                 ("all", date.min, date.max)):
            dialog.date_range.mode_input.setCurrentIndex(dialog.date_range.mode_input.findData(mode))
            self.assertEqual((dialog._criteria().start, dialog._criteria().end), (start, end))
        dialog.date_range.set_custom_range(date(2024, 2, 1), date(2024, 2, 29))
        self.assertEqual(dialog._criteria().end, date(2024, 2, 29))
        dialog.reject()
        self.window._job_runner = ImmediateJobRunner()
        self.window.calendar_page.date_selected.emit(date(2024, 2, 29))
        self.assertEqual(self.window.current_month, date(2024, 2, 1))
        self.assertEqual(self.window.selected_day, date(2024, 2, 29))

    def test_worker_editor_changes_are_applied_only_on_completion_and_failures_restart_display(self):
        from worklogger.app.job_runner import CancellationToken, JobHandle
        from worklogger.domain.shared.errors import InfrastructureError
        class DeferredRunner:
            def submit(self, name, operation, *, on_complete):
                self.operation, self.complete = operation, on_complete
                return JobHandle(name, lambda: None)
        panel = self.panel
        runner = DeferredRunner()
        panel._job_runner = runner
        panel.start_input.setText("09:00")
        panel.end_input.setText("10:00")
        panel.content_input.setPlainText("Pending content")
        panel.view_model.update(start="09:00", end="10:00", entry_type="normal", content="Pending content",
                                work_mode=WorkMode.REMOTE)
        panel._save()
        before = panel.view_model.draft
        result = runner.operation(CancellationToken())
        self.assertEqual(panel.view_model.draft, before)
        self.assertIsNone(panel.view_model.draft.original)
        self.assertEqual(result.value.editor.draft.work_mode, WorkMode.REMOTE)
        runner.complete(result)
        self.assertIsNotNone(panel.view_model.draft.original)
        self.assertEqual(panel.view_model.draft.original.work_mode, WorkMode.REMOTE)
        self.assertEqual(panel.view_model.auto_work_mode, WorkMode.REMOTE)
        panel._job_runner = ImmediateJobRunner()
        panel.view_model.clear(self.now.date())
        self.now += timedelta(hours=2)
        panel._job_runner = runner
        panel._start_with_content("normal", "Active timer")
        started = runner.operation(CancellationToken())
        self.assertIsNone(panel.view_model.timer)
        runner.complete(started)
        self.assertIsNotNone(panel.view_model.timer)
        panel.time_tabs.setCurrentIndex(1)
        panel.content_input.setPlainText("Updated timer")
        panel._submit(lambda model: model.save_content())
        updated = runner.operation(CancellationToken())
        self.assertEqual(panel.view_model.timer.content, "Active timer")
        runner.complete(updated)
        self.assertEqual(panel.view_model.timer.content, "Updated timer")
        panel._submit(lambda model: Result.failure(InfrastructureError("worklog_save_failed", "worklog_save_failed")))
        runner.complete(runner.operation(CancellationToken()))
        self.assertFalse(panel.is_busy)
        self.assertTrue(panel.auto_timer.isActive())

    def test_full_day_calendar_event_requires_an_explicit_work_period(self):
        with patch.object(self.panel.view_model.service, "default_work_mode", return_value=WorkMode.REMOTE):
            self.panel.copy_event(CalendarEvent(None, self.runtime.user.id, self.now.date(), "Trip", "00:00", "24:00"))
        self.assertEqual((self.panel.start_input.text(), self.panel.end_input.text()), ("", ""))
        self.assertEqual(self.panel.content_input.toPlainText(), "Trip")
        self.assertIsNone(self.panel.view_model.draft.work_mode)

    def test_record_modes_share_content_classification_and_saved_identity(self):
        panel = self.panel
        panel.view_model.update(start="", end="", entry_type="normal", content="", work_mode=WorkMode.REMOTE)
        panel.start_input.setText("09:00")
        panel.end_input.setText("10:00")
        apply_classification(panel, "meeting")
        panel.content_input.setPlainText("Agenda")
        panel.save_button.click()
        saved = self.repository.list_for_day(self.runtime.user.id, self.now.date())[0]
        self.assertEqual(saved.work_mode, WorkMode.REMOTE)
        panel.time_tabs.setCurrentIndex(1)
        self.assertEqual(panel.content_input.toPlainText(), "Agenda")
        self.assertEqual(editor_state(panel).entry_type, "meeting")
        self.assertEqual(panel.view_model.auto_completed.id, saved.id)
        self.assertEqual(panel.view_model.editor_state(automatic=True).work_mode, WorkMode.REMOTE)
        panel.view_model.update_auto(content="Agenda", entry_type="meeting", context=saved.context,
                                     work_mode=WorkMode.ONSITE)
        self.assertTrue(panel.view_model.auto_dirty)
        panel.view_model.discard_changes()
        self.assertFalse(panel.view_model.auto_dirty)
        self.assertEqual(panel.view_model.auto_work_mode, WorkMode.REMOTE)
        panel.view_model.update_auto(content="Agenda", entry_type="meeting", context=saved.context, work_mode=None)
        self.assertTrue(panel.view_model.auto_dirty)
        apply_classification(panel, "training")
        panel.content_input.setPlainText("Training agenda")
        panel.save_button.click()
        edited = self.repository.get_entry(self.runtime.user.id, saved.id)
        self.assertEqual((edited.note, edited.entry_type.value), ("Training agenda", "training"))
        self.assertIsNone(edited.work_mode)
        self.assertIsNone(panel.view_model.draft.work_mode)
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
        self.assertEqual(editor_state(panel).entry_type, "normal")
        self.assertIsNone(panel.view_model.auto_completed)

    def test_active_timer_content_is_shared_without_editable_manual_boundaries(self):
        panel = self.panel
        panel.view_model.update(start="", end="", entry_type="normal", content="", work_mode=WorkMode.BUSINESS_TRIP)
        panel.content_input.setPlainText("Initial description")
        panel.time_tabs.setCurrentIndex(1)
        panel.clock_in_button.click()
        self.assertEqual(panel.view_model.timer.work_mode, WorkMode.BUSINESS_TRIP)
        self.assertEqual(panel.view_model.editor_state(automatic=True).work_mode, WorkMode.BUSINESS_TRIP)
        panel.content_input.setPlainText("Active description")
        panel.time_tabs.setCurrentIndex(0)
        self.assertEqual(panel.content_input.toPlainText(), "Active description")
        self.assertFalse(panel.start_input.isEnabled())
        self.assertFalse(panel.classification_button.isEnabled())
        self.assertEqual(panel.view_model.editor_state(automatic=False).work_mode, WorkMode.BUSINESS_TRIP)
        panel.content_input.setPlainText("Revised description")
        panel.save_button.click()
        self.assertEqual(panel.view_model.timer.content, "Revised description")
        self.assertEqual(panel.view_model.timer.work_mode, WorkMode.BUSINESS_TRIP)
        panel.time_tabs.setCurrentIndex(1)
        self.assertEqual(panel.content_input.toPlainText(), "Revised description")
        self.now += timedelta(hours=1)
        panel.clock_out_button.click()
        panel.time_tabs.setCurrentIndex(0)
        self.assertEqual(panel.content_input.toPlainText(), "Revised description")
        self.assertEqual(panel.view_model.draft.original.note, "Revised description")
        self.assertEqual(panel.view_model.draft.original.work_mode, WorkMode.BUSINESS_TRIP)
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
            def handle(self, command, cancellation_token=None):
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
        popup = open_classification(self.panel)
        picker = popup.context_picker
        self.assertTrue(picker.recent_button.isEnabled())
        picker.recent_menu.actions()[0].trigger()
        self.assertEqual(picker.context().work_item_id, item.id)
        popup.apply_button.click()
        self.assertEqual(editor_state(self.panel).context.work_item_id, item.id)
        self.assertEqual(self.panel.content_input.toPlainText(), "Unsaved editor content")
        dialog.close()

    def test_project_records_display_and_preserve_the_fixed_context(self):
        from worklogger.domain.projects.models import WorkContext
        from worklogger.domain.worklog.search import EntryFilter
        from worklogger.presentation.widgets.record_search import RecordSearchDialog
        service = self.panel.view_model.service
        project = service.projects.save_project("Research").value
        item = service.projects.save_work_item(project.id, "Review").value
        day = self.now.date()
        service.save_manual(day, "09:00", "10:00", "normal", "<b>Agenda</b>\n" + "Details " * 30,
                            context=WorkContext(project.id, item.id))
        service.save_manual(day, "10:00", "11:00", "normal", "Agenda")
        criteria = EntryFilter(day, day, project_id=project.id, work_item_id=item.id)
        dialog = RecordSearchDialog(self.panel.view_model, day, self.window,
                                    job_runner=ImmediateJobRunner(), criteria=criteria)
        self.addCleanup(dialog.deleteLater)
        try:
            self.assertEqual(dialog.project_combo.currentData(), project.id)
            self.assertEqual(dialog.item_combo.currentData(), item.id)
            self.assertEqual(dialog.project_combo.currentText(), project.name)
            self.assertEqual(dialog.item_combo.currentText(), item.title)
            self.assertFalse(dialog.project_combo.isEnabled())
            self.assertFalse(dialog.item_combo.isEnabled())
            dialog.search_input.setText("Agenda")
            dialog.search_input.returnPressed.emit()
            self.assertEqual(dialog.results.topLevelItemCount(), 1)
            row = dialog.results.topLevelItem(0)
            self.assertEqual(row.data(0, Qt.ItemDataRole.UserRole).context.project_id, project.id)
            self.assertTrue(row.text(5).endswith("..."))
            self.assertIn("&lt;b&gt;Agenda&lt;/b&gt;", row.toolTip(5))
        finally:
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
        panel._split_record(original)
        dialog = panel._record_boundary_dialog
        apply_boundary(dialog, datetime.combine(original.day, datetime.min.time()).replace(hour=10))
        self.assertEqual(dialog.preview.topLevelItemCount(), 2)
        dialog.confirm_button.click()
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

    def test_overlap_dialog_preserves_cancelled_input_and_saves_the_selected_replacement(self):
        panel = self.panel
        original = panel.view_model.service.save_manual(self.now.date(), "09:00", "18:00", "meeting", "Work").value
        self.window.refresh()
        panel.start_input.setText("12:00")
        panel.end_input.setText("13:00")
        apply_classification(panel, "break")
        panel.content_input.setPlainText("Lunch")
        panel.save_button.click()
        dialog = panel._replacement_dialog
        self.assertIsNotNone(dialog)
        self.assertEqual(dialog.preview.topLevelItemCount(), 3)
        dialog.whole_button.click()
        self.assertEqual(dialog.preview.topLevelItemCount(), 1)
        dialog.reject()
        self.assertEqual(self.repository.list_for_day(self.runtime.user.id, self.now.date()), (original,))
        self.assertEqual((panel.start_input.text(), panel.end_input.text(), panel.content_input.toPlainText()),
                         ("12:00", "13:00", "Lunch"))
        panel.save_button.click()
        panel._replacement_dialog.confirm_button.click()
        records = self.repository.list_for_day(self.runtime.user.id, self.now.date())
        self.assertEqual(len(records), 3)
        self.assertEqual(sum(record.worked_hours() for record in records), 8)
        with patch("worklogger.presentation.widgets.time_entries.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            panel.undo_button.click()
        self.assertEqual(len(self.repository.list_for_day(self.runtime.user.id, self.now.date())), 1)
        self.warning.assert_not_called()

    def test_record_boundary_preview_validates_clock_times_and_historical_breaks(self):
        from zoneinfo import ZoneInfo
        from worklogger.domain.worklog.models import WorkLog
        from worklogger.presentation.widgets.record_edit_dialogs import RecordBoundaryDialog

        historical = WorkLog(self.runtime.user.id, self.now.date(), "09:00", "18:00", 1, "Previous work")
        dialog = RecordBoundaryDialog(historical, self.panel, historical_break=True)
        self.addCleanup(dialog.deleteLater)
        wall = datetime.combine(historical.day, datetime.min.time())
        apply_boundary(dialog, wall.replace(hour=12))
        self.assertEqual(dialog.chosen_minutes(), 180)
        self.assertEqual(dialog.preview.topLevelItemCount(), 3)
        apply_boundary(dialog, wall.replace(hour=18))
        self.assertFalse(dialog.confirm_button.isEnabled())
        self.assertEqual(dialog.preview.topLevelItemCount(), 0)
        zone = ZoneInfo("America/New_York")
        start = datetime(2026, 11, 1, 0, 30, tzinfo=zone)
        record = WorkLog(self.runtime.user.id, start.date(), "00:30", "03:30",
                         started_at=start, ended_at=start.replace(hour=3))
        split = RecordBoundaryDialog(record, self.panel, zone=zone)
        self.addCleanup(split.deleteLater)
        self.assertEqual(split.chosen_minutes(), 120)
        apply_boundary(split, datetime(2026, 11, 1, 1, 30))
        self.assertEqual(split.offset_combo.count(), 2)
        split.offset_combo.setCurrentIndex(1)
        self.assertEqual(split.chosen_minutes(), 120)
        self.assertTrue(split.confirm_button.isEnabled())
        apply_boundary(split, datetime(2026, 11, 1, 3, 30))
        self.assertFalse(split.confirm_button.isEnabled())

    def test_overnight_edits_refresh_both_calendar_dates_and_undo_across_years(self):
        panel, day, tomorrow = self.panel, date(2026, 12, 31), date(2027, 1, 1)
        old = panel.view_model.service.save_manual(day, "22:00", "06:00", "meeting", "Night work").value
        self.assertTrue(self.window.select_day(day))
        panel._split_record(old)
        dialog = panel._record_boundary_dialog
        apply_boundary(dialog, datetime(2026, 12, 31, 0))
        self.assertFalse(dialog.confirm_button.isEnabled())
        apply_boundary(dialog, datetime(2027, 1, 1, 0))
        self.assertTrue(dialog.confirm_button.isEnabled())
        self.assertEqual([(dialog.preview.topLevelItem(index).text(0), dialog.preview.topLevelItem(index).text(1))
                          for index in range(2)],
                         [("2026-12-31", "22:00 - 00:00 (+1)"), ("2027-01-01", "00:00 - 06:00")])
        dialog.confirm_button.click()
        cells = {cell.day: cell for cell in self.window.calendar_page.calendar_view.state.cells}
        self.assertEqual((cells[day].worked_hours, cells[tomorrow].worked_hours), (2, 6))
        with patch("worklogger.presentation.widgets.time_entries.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            panel.undo_button.click()
        self.assertTrue(self.window.select_day(tomorrow))
        self.assertTrue(panel.new_record())
        panel.start_input.setText("00:00")
        panel.end_input.setText("01:00")
        apply_classification(panel, "break")
        panel.content_input.setPlainText("Rest")
        panel.save_button.click()
        replacement = panel._replacement_dialog
        self.assertIsNotNone(replacement)
        self.assertEqual(replacement.preview.topLevelItemCount(), 3)
        replacement.confirm_button.click()
        cells = {cell.day: cell for cell in self.window.calendar_page.calendar_view.state.cells}
        self.assertEqual((cells[day].worked_hours, cells[tomorrow].worked_hours), (2, 5))
        records = self.repository.list_entries_range(self.runtime.user.id, day, tomorrow)
        self.assertEqual(len(records), 3)
        with patch("worklogger.presentation.widgets.time_entries.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            panel.undo_button.click()
        cells = {cell.day: cell for cell in self.window.calendar_page.calendar_view.state.cells}
        self.assertEqual((cells[day].worked_hours, cells[tomorrow].worked_hours), (8, 0))
        restored, = self.repository.list_entries_range(self.runtime.user.id, day, tomorrow)
        self.assertEqual((restored.id, restored.day, restored.start_time, restored.end_time), (old.id, day, "22:00", "06:00"))
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
        popup = open_classification(panel)
        picker = popup.context_picker
        self.assertIsNone(picker.project_combo.currentData())
        self.assertFalse(picker.work_item_combo.isEnabled())
        picker.project_combo.setCurrentIndex(picker.project_combo.findData(project.id))
        self.assertTrue(picker.work_item_combo.isEnabled())
        picker.work_item_combo.setCurrentIndex(picker.work_item_combo.findData(item.id))
        picker.project_combo.setCurrentIndex(picker.project_combo.findData(None))
        self.assertFalse(picker.work_item_combo.isEnabled())
        self.assertIsNone(picker.work_item_combo.currentData())
        picker.project_combo.setCurrentIndex(picker.project_combo.findData(project.id))
        self.assertTrue(picker.work_item_combo.isEnabled())
        picker.work_item_combo.setCurrentIndex(picker.work_item_combo.findData(item.id))
        popup.apply_button.click()
        panel.start_input.setText("09:00")
        panel.end_input.setText("10:00")
        panel.content_input.setPlainText("Completed review")
        panel.save_button.click()
        record = self.repository.list_for_day(self.runtime.user.id, self.now.date())[0]
        self.assertEqual(record.context.label, "Research / Review")
        self.assertIn(record.context.label, self.window.calendar_page.records_widget.entry_buttons[record.id].label.text())
        panel.edit_entry(record)
        popup = open_classification(panel)
        picker = popup.context_picker
        self.assertEqual(picker.work_item_combo.currentData(), item.id)
        popup.cancel_button.click()
        panel.clear_button.click()
        panel.time_tabs.setCurrentIndex(1)
        popup = open_classification(panel)
        picker = popup.context_picker
        picker.project_combo.setCurrentIndex(picker.project_combo.findData(project.id))
        picker.work_item_combo.setCurrentIndex(picker.work_item_combo.findData(item.id))
        popup.apply_button.click()
        self.now += timedelta(hours=1)
        panel.clock_in_button.click()
        self.assertFalse(panel.classification_button.isEnabled())
        self.now += timedelta(hours=1)
        panel.clock_out_button.click()
        self.assertTrue(panel.classification_button.isEnabled())
        timed = self.repository.list_for_day(self.runtime.user.id, self.now.date())[-1]
        self.assertEqual(timed.context, record.context)
        self.assertEqual(editor_state(panel).entry_type, "normal")
        dialog.work_item_title_input.setText("Unsaved rename")
        with patch("worklogger.presentation.widgets.project_manager.QMessageBox.question", return_value=QMessageBox.StandardButton.No):
            dialog.editor_tabs.setCurrentIndex(0)
            self.assertEqual(dialog.editor_tabs.currentIndex(), 1)
            self.assertEqual(dialog.work_item_title_input.text(), "Unsaved rename")
        with patch("worklogger.presentation.widgets.project_manager.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            dialog.editor_tabs.setCurrentIndex(0)
            dialog.project_archive_button.click()
        panel.edit_entry(record)
        popup = open_classification(panel)
        picker = popup.context_picker
        self.assertEqual(picker.context().project_id, project.id)
        popup.cancel_button.click()
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
        panel.view_model.auto_entry_type = "meeting"
        panel.view_model.auto_content = "Timed meeting"
        panel.view_model.auto_work_mode = WorkMode.OTHER
        draft = panel.view_model.draft
        self.window.hide()
        self.assertTrue(controller._start_action.isEnabled())
        self.assertFalse(controller._end_action.isEnabled())
        controller._start_action.trigger()
        self.assertFalse(controller._start_action.isEnabled())
        self.assertTrue(controller._end_action.isEnabled())
        self.assertEqual(panel.view_model.timer.entry_type.value, "meeting")
        self.assertEqual(panel.view_model.timer.work_mode, WorkMode.OTHER)
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
        self.assertEqual((entry.note, entry.entry_type.value, entry.worked_hours()), ("Timed meeting", "meeting", 1))
        self.assertEqual(entry.work_mode, WorkMode.OTHER)
        self.assertEqual(panel.view_model.draft, draft)
        self.assertTrue(self.window.isHidden())
        panel.clear_button.click()
        self.warning.assert_not_called()

    def test_custom_type_management_and_manual_automatic_recording_preserve_saved_categories(self):
        from worklogger.presentation.widgets.entry_type_manager import EntryTypeManagerDialog
        from worklogger.presentation.settings import SettingsWorkflowController
        from worklogger.presentation.viewmodels.entry_types import EntryTypeManagerViewModel
        from tests.presentation.test_settings_presentation import _view_model, MemorySettingsRepository
        from tests.presentation.test_settings_workflow import FakeAuthViewModel, FakeDataManagementViewModel
        panel = self.panel
        controller = SettingsWorkflowController(settings_view_model=_view_model(MemorySettingsRepository()),
            auth_view_model=FakeAuthViewModel(), user=self.runtime.user,
            data_management_view_model=FakeDataManagementViewModel(),
            entry_types_view_model=EntryTypeManagerViewModel(panel.view_model.service.entry_types))
        settings = controller.create_page()
        self.addCleanup(settings.deleteLater)
        settings.entry_types_changed.connect(panel.refresh_entry_types)
        definitions = []

        def create_type(dialog):
            dialog.name_input.setText("Research")
            dialog.category_combo.setCurrentIndex(dialog.category_combo.findData("work"))
            dialog.save_button.click()
            definitions.append(dialog.type_list.currentItem().data(256))
            return 1

        with patch.object(EntryTypeManagerDialog, "exec", create_type):
            settings.manage_entry_types_button.click()
        definition = definitions[0]
        apply_classification(panel, definition.value)
        panel.start_input.setText("09:00")
        panel.end_input.setText("10:00")
        catalog = panel.view_model.service.entry_types
        with patch.object(catalog, "list_types", wraps=catalog.list_types) as reads:
            panel.content_input.setPlainText("Research draft")
            panel.content_input.setPlainText("Research details")
            reads.assert_not_called()
        panel.save_button.click()
        first = self.repository.list_for_day(self.runtime.user.id, self.now.date())[0]
        self.assertEqual((first.entry_type.label, first.worked_hours()), ("Research", 1))
        self.assertEqual(editor_state(panel).entry_type, definition.value)
        self.assertTrue(panel.new_record())
        self.assertEqual(editor_state(panel).entry_type, "normal")
        panel.time_tabs.setCurrentIndex(1)
        self.now += timedelta(hours=1)
        apply_classification(panel, definition.value)
        panel.clock_in_button.click()
        panel.content_input.setPlainText("Ongoing research")

        def edit_type(dialog):
            dialog.type_list.setCurrentRow(0)
            dialog.name_input.setText("Study")
            dialog.category_combo.setCurrentIndex(dialog.category_combo.findData("break"))
            dialog.save_button.click()
            return 1

        with patch.object(EntryTypeManagerDialog, "exec", edit_type):
            settings.manage_entry_types_button.click()
        self.assertIn("Research", panel.classification_button.accessibleDescription())
        self.assertEqual(panel.content_input.toPlainText(), "Ongoing research")
        self.assertEqual(panel.view_model.timer.entry_type.category, "work")
        self.now += timedelta(hours=1)
        panel.clock_out_button.click()
        self.assertEqual(len(self.repository.list_for_day(self.runtime.user.id, self.now.date())), 2)
        panel.edit_entry(first)
        panel.content_input.setPlainText("Revised description")
        panel.save_button.click()
        self.assertEqual(self.repository.get_entry(self.runtime.user.id, first.id).entry_type.label, "Research")
        self.assertEqual(sum(entry.worked_hours() for entry in self.repository.list_for_day(self.runtime.user.id, self.now.date())), 2)
        self.warning.assert_not_called()

    def test_work_mode_defaults_do_not_replace_historical_values_or_explicit_absence(self):
        model = self.panel.view_model
        with patch.object(model.service, "default_work_mode", return_value=WorkMode.REMOTE):
            model.new(self.now.date())
            self.assertEqual(model.draft.work_mode, WorkMode.REMOTE)
            self.assertEqual(model.auto_work_mode, WorkMode.REMOTE)
            model.update(start="07:00", end="08:00", entry_type="meeting", content="Planning")
            self.assertEqual(model.draft.work_mode, WorkMode.REMOTE)
            self.assertTrue(model.save_manual().ok)
            historical = model.draft.original
            model.new(self.now.date())
            model.select(historical)
            model.update(start="07:00", end="08:00", entry_type="meeting", content="Planning", work_mode=None)
            self.assertTrue(model.manual_dirty)
            model.discard_changes()
            self.assertFalse(model.manual_dirty)
            self.assertEqual(model.draft.work_mode, WorkMode.REMOTE)
            model.update(start="07:00", end="08:00", entry_type="meeting", content="Planning", work_mode=None)
            self.assertTrue(model.save_manual().ok)
            unspecified = model.draft.original
            model.new(self.now.date())
            self.assertEqual(model.draft.work_mode, WorkMode.REMOTE)
            model.select(unspecified)
            self.assertIsNone(model.draft.work_mode)
            self.assertIsNone(model.editor_state(automatic=False).work_mode)

            model.new(self.now.date())
            model.update(start="09:00", end="", entry_type="normal", content="Independent work")
            draft = model.draft
            model.auto_work_mode = WorkMode.ONSITE
            self.assertTrue(model.start("normal", "Independent work").ok)
            self.assertEqual(model.draft, draft)
            self.assertFalse(model.editing_active_timer)
            self.assertEqual(model.timer.work_mode, WorkMode.ONSITE)
            self.now += timedelta(hours=1)
            self.assertTrue(model.finish().ok)
            self.assertEqual(model.draft, draft)
            self.assertEqual(model.auto_completed.work_mode, WorkMode.ONSITE)

    def test_manual_nonwork_records_remain_independent_of_automatic_work(self):
        from worklogger.domain.projects.models import WorkContext

        model = self.panel.view_model
        custom_break = model.service.entry_types.save("Rest", "break").value
        custom_leave = model.service.entry_types.save("Leave", "leave").value
        from worklogger.presentation.viewmodels.time_entries import TimeEntryViewModel
        model = TimeEntryViewModel(model.service)
        with patch.object(model.service, "default_work_mode", return_value=WorkMode.REMOTE):
            for entry_type in ("break", "paid_leave", custom_break.value, custom_leave.value):
                with self.subTest(entry_type=entry_type):
                    model.new(self.now.date())
                    model.update(start="07:00", end="08:00", entry_type=entry_type, content="Manual record")
                    self.assertIsNone(model.draft.work_mode)
                    self.assertTrue(model.save_manual().ok)
                    draft = model.draft
                    self.assertFalse(model.manual_dirty)
                    self.assertIsNone(model.auto_completed)
                    self.assertEqual(model.auto_entry_type, "normal")
                    self.assertEqual(model.auto_work_mode, WorkMode.REMOTE)
                    model.update_auto(content="Automatic work", entry_type="normal", context=WorkContext())
                    self.assertEqual(model.draft, draft)
                    self.assertTrue(model.start("normal", model.auto_content).ok)
                    self.assertFalse(model.editing_active_timer)
                    self.now += timedelta(hours=1)
                    self.assertTrue(model.finish().ok)
                    self.assertEqual(model.draft, draft)
                    self.assertEqual(model.auto_completed.work_mode, WorkMode.REMOTE)
                    model.update_auto(content="Updated work", entry_type="normal", context=WorkContext(), work_mode=None)
                    self.assertTrue(model.auto_dirty)
                    self.assertTrue(model.save_content().ok)
                    self.assertIsNone(model.auto_completed.work_mode)
                    self.assertEqual(model.draft, draft)
                    self.now = (self.now + timedelta(days=1)).replace(hour=9)

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
        self.addCleanup(lambda: self.runtime.job_runner.shutdown(wait=True))
        self.addCleanup(self.window.close)
        self.panel = self.window.entry_panel
        self.panel._job_runner = ImmediateJobRunner()
        self.window._job_runner = self.panel._job_runner
        self.panel._polish_task._runner = self.panel._job_runner
        self.repository = SQLiteWorkLogRepository(result.value.connection_factory)
        self.now = datetime(2026, 5, 20, 9, tzinfo=self.panel.view_model.service.local_timezone)
        self.panel.view_model.service._clock = lambda: self.now
        self.assertTrue(self.window.refresh())

    def test_clock_selection_and_polishing_change_only_the_local_draft(self):
        panel = self.panel
        panel.start_input.setText("09:00")
        panel.end_input.setText("10:00")
        apply_classification(panel, "meeting")
        panel.content_input.setPlainText("Draft description")
        from worklogger.presentation.widgets.time_picker import TimePickerDialog
        panel.start_input.actions()[0].trigger()
        picker = panel.findChild(TimePickerDialog)
        picker.time_input.setTime(QTime(9, 15))
        picker.select_button.click()
        commands = []
        class Rewriter:
            available = True
            def handle(self, command, cancellation_token=None):
                commands.append(command)
                return Result.success(RewriteTextResult("Prepared agenda"))
        panel.view_model._rewrite_handler = Rewriter()
        panel.refresh_ai_availability()
        panel.polish_button.click()
        self.assertEqual(panel.content_input.toPlainText(), "Prepared agenda")
        self.assertEqual((panel.start_input.text(), panel.end_input.text(), editor_state(panel).entry_type), ("09:15", "10:00", "meeting"))
        self.assertEqual(commands[0].context, "time_entry")
        self.assertEqual(self.repository.list_for_day(self.runtime.user.id, self.now.date()), ())
        panel.clear_button.click()

    def test_manual_create_select_update_and_delete_periods(self):
        panel = self.panel
        popup = open_classification(panel)
        self.assertGreaterEqual(popup.period_type_combo.findData("other"), 0)
        self.assertEqual(popup.period_type_combo.findData("remote"), -1)
        self.assertEqual(popup.period_type_combo.findData("business_trip"), -1)
        popup.cancel_button.click()
        for start, end, kind, content in (("09:00", "11:00", "meeting", "Planning"),
                                         ("11:00", "12:00", "training", "Practice")):
            self.assertTrue(panel.new_record())
            panel.start_input.setText(start)
            panel.end_input.setText(end)
            apply_classification(panel, kind)
            panel.content_input.setPlainText(content)
            panel.save_button.click()
            self.assertEqual(editor_state(panel).entry_type, kind)
            self.assertEqual(panel.start_input.text(), start)
            self.assertEqual(panel.content_input.toPlainText(), content)
        entries = self.repository.list_for_day(self.runtime.user.id, self.now.date())
        self.assertEqual(len(entries), 2)
        self.assertEqual([entry.entry_type.value for entry in entries], ["meeting", "training"])
        records = self.window.calendar_page.records_widget.entry_buttons
        self.assertEqual(len(records), 2)
        current = records[entries[0].id]
        current.click()
        self.assertEqual(panel.view_model.draft.original.id, entries[0].id)
        self.assertEqual(editor_state(panel).entry_type, "meeting")
        panel.content_input.setPlainText("Updated planning")
        panel.save_button.click()
        self.assertEqual(len(self.repository.list_for_day(self.runtime.user.id, self.now.date())), 2)
        self.assertEqual(editor_state(panel).entry_type, "meeting")
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
        apply_classification(panel, "meeting")
        panel.content_input.setPlainText("Planning")
        panel.clock_in_button.click()
        self.assertFalse(panel.break_button.isEnabled())
        panel.break_button.click()
        self.assertEqual(self.repository.list_for_day(self.runtime.user.id, self.now.date()), ())
        panel.content_input.setPlainText("Agenda")
        panel.save_button.click()
        self.assertEqual(self.repository.list_for_day(self.runtime.user.id, self.now.date()), ())
        self.assertEqual(panel.view_model.service.timer.content, "Agenda")
        self.assertEqual(editor_state(panel).entry_type, "meeting")
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
        self.assertEqual((entries[-1].entry_type.value, entries[-1].start_time, entries[-1].end_time), ("break", "12:00", "13:00"))
        self.assertIsNone(panel.view_model.service.timer)
        self.assertEqual(editor_state(panel).entry_type, "normal")
        self.assertEqual(panel.view_model.draft.entry_type, "break")
        panel.clear_button.click()
        self.assertEqual(editor_state(panel).entry_type, "normal")
        self.now += timedelta(hours=1)
        panel._tick()
        self.assertIsNone(panel.view_model.service.timer)
        apply_classification(panel, "meeting")
        panel.clock_in_button.click()
        self.assertEqual(panel.view_model.service.timer.entry_type.value, "meeting")
        self.now = self.now.replace(hour=16, minute=0)
        panel.content_input.setPlainText("Review")
        panel.clock_out_button.click()
        self.assertEqual(editor_state(panel).entry_type, "meeting")
        entries = self.repository.list_for_day(self.runtime.user.id, self.now.date())
        self.assertEqual(len(entries), 3)
        self.assertEqual([entry.entry_type.value for entry in entries], ["meeting", "break", "meeting"])
        self.assertEqual(self.repository.get_for_day(self.runtime.user.id, self.now.date()).worked_hours(), 6)
        panel.content_input.setPlainText("Updated review")
        panel.save_button.click()
        self.assertEqual(self.repository.get_entry(self.runtime.user.id, entries[-1].id).note, "Updated review")
        self.assertEqual(len(self.repository.list_for_day(self.runtime.user.id, self.now.date())), 3)
        self.assertEqual(editor_state(panel).entry_type, "meeting")
        panel.clear_button.click()
        self.assertEqual(editor_state(panel).entry_type, "normal")
        panel.clock_in_button.click()
        self.assertEqual(panel.view_model.service.timer.entry_type.value, "normal")
        self.warning.assert_not_called()

    def test_break_shortcut_records_without_starting_a_timer(self):
        panel = self.panel
        panel.time_tabs.setCurrentIndex(1)
        self.assertTrue(panel.break_button.isEnabled())
        panel.content_input.setPlainText("Lunch")
        panel.break_button.click()
        entries = self.repository.list_for_day(self.runtime.user.id, self.now.date())
        self.assertEqual(len(entries), 1)
        self.assertEqual((entries[0].entry_type.value, entries[0].start_time, entries[0].end_time), ("break", "09:00", "10:00"))
        self.assertIsNone(panel.view_model.service.timer)
        self.assertFalse(panel.clock_out_button.isEnabled())
        card = self.window.calendar_page.records_widget.entry_buttons[entries[0].id]
        self.assertIn("09:00 - 10:00", card.label.text())
        panel.edit_entry(entries[0])
        panel.content_input.setPlainText("Updated lunch")
        panel.save_button.click()
        self.assertEqual(self.repository.get_entry(self.runtime.user.id, entries[0].id).note, "Updated lunch")
        panel.time_tabs.setCurrentIndex(1)
        self.assertEqual(editor_state(panel).entry_type, "normal")
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
