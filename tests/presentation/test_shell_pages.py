from __future__ import annotations

from dataclasses import replace
from datetime import date
import os
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QLabel, QFileDialog
from worklogger.presentation.job_runner import ImmediateJobRunner

from worklogger.domain.shared.result import Result
from worklogger.domain.reporting.history import ReportHistoryPage
from worklogger.domain.shared.errors import CancellationError, ValidationError
from worklogger.app.job_runner import JobHandle, CancellationToken
from worklogger.presentation.reporting.dialog import ReportTemplateDialog
from worklogger.presentation.shell.pages import ReportsPage
from worklogger.presentation.viewmodels.reports import ReportEditorState
from worklogger.presentation.widgets.report_history import ReportHistoryDisplayItem
from tests.presentation.test_app_window import MemoryWorkLogRepository, _window


class ReportsViewModel:
    def __init__(self) -> None:
        self.loads: list[tuple[str, date]] = []

    def load(self, report_type: str, day: date):
        self.loads.append((report_type, day))
        return Result.success(ReportEditorState(1, report_type, day, day, "Original " + report_type))

    def browse_history(self, criteria, *, cursor=None):
        return Result.success(ReportHistoryPage())

    def save(self, state: ReportEditorState, content: str):
        return Result.success(replace(state, content=content, saved=True))


class ShellPagesTests(unittest.TestCase):
    def test_background_exports_retain_content_and_dates_and_restore_controls(self):
        class Model(ReportsViewModel):
            timesheet_available = True
            saved_export_available = True

            def export_markdown(self, destination, content):
                self.exported = (destination, content)
                return Result.success(destination)

            def export_saved_daily(self, destination, day, *, whole_month):
                self.exported = (destination, day, whole_month)
                return Result.success(destination)

            def export_timesheet(self, destination, day, *, whole_month, file_format):
                self.exported = (destination, day, whole_month, file_format)
                return Result.success(destination)

        class Runner:
            def submit(self, name, job, *, on_complete):
                self.job, self.complete = job, on_complete
                return JobHandle(name, lambda: None)

        day, destination = date(2026, 10, 16), Path("report-export")
        model = Model()
        page = ReportsPage(model, day, job_runner=ImmediateJobRunner())
        self.addCleanup(page.deleteLater)
        page.refresh()
        runner = Runner()
        page._job_runner = runner
        for scope, expected in (("current", (destination, "Visible draft")),
                                ("month", (destination, day, True)),
                                ("timesheet_day_pdf", (destination, day, False, "pdf"))):
            page._selected_day = day
            page.editor.setPlainText("Visible draft")
            with patch.object(QFileDialog, "getSaveFileName", return_value=(str(destination), "")):
                page._choose_export_scope(scope)
            self.assertTrue(page.is_busy)
            self.assertTrue(page.editor.isReadOnly())
            self.assertFalse(page.previous_period_button.isEnabled())
            page._selected_day = date(2027, 1, 1)
            page.editor.setPlainText("Later content")
            runner.complete(runner.job(CancellationToken()))
            self.assertEqual(model.exported, expected)
            self.assertFalse(page.is_busy)
            self.assertFalse(page.editor.isReadOnly())
            self.assertEqual(page.editor.toPlainText(), "Later content")

    def test_report_and_history_loads_preserve_control_states(self):
        class Model(ReportsViewModel):
            revisions_available = True
            content = "Saved report"

            def load(self, kind, day):
                return Result.success(ReportEditorState(1, kind, day, day, self.content,
                                                       saved=True, report_id=42))

        class Runner:
            def submit(self, name, job, *, on_complete):
                self.name, self.job, self.complete = name, job, on_complete
                return JobHandle("pending", lambda: None)

        class Observer(QObject):
            def __init__(self, parent):
                super().__init__(parent)
                self.changes = []

            def eventFilter(self, watched, event):
                if event.type() == QEvent.Type.EnabledChange:
                    self.changes.append(watched)
                return False

        model = Model()
        page = ReportsPage(model, date(2026, 10, 11), job_runner=ImmediateJobRunner())
        self.addCleanup(page.deleteLater)
        page.refresh()
        controls = (page.report_type_control, page.previous_period_button, page.next_period_button,
                    page.templates_button, page.generate_button, page.versions_button,
                    page.ai_assist_button, page.ai_hint_line_edit, page.save_button,
                    page.copy_button, page.export_current_button, page.history_panel)
        enabled = tuple(control.isEnabled() for control in controls)
        observer = Observer(page)
        for control in controls:
            control.installEventFilter(observer)
        runner = Runner()
        page._job_runner = runner
        model.content = "Updated report"
        self.assertTrue(page.refresh())
        self.assertTrue(page.is_busy)
        self.assertTrue(page.editor.isReadOnly())
        self.assertEqual(tuple(control.isEnabled() for control in controls), enabled)
        QTest.qWait(200)
        self.assertFalse(page.load_progress.isHidden())
        self.assertEqual(tuple(control.isEnabled() for control in controls), enabled)
        page.generate_button.click()
        page.templates_button.click()
        self.assertEqual(runner.name, "load_reports")
        runner.complete(runner.job(CancellationToken()))
        self.assertEqual(page.editor.toPlainText(), "Updated report")
        self.assertFalse(page.has_unsaved_changes)
        self.assertFalse(page.editor.isReadOnly())
        self.assertTrue(page.load_progress.isHidden())
        page._refresh_history()
        runner.complete(runner.job(CancellationToken()))
        self.assertEqual(tuple(control.isEnabled() for control in controls), enabled)
        self.assertEqual(observer.changes, [])

    def test_slow_report_load_protects_editor_and_recovers_after_failure(self):
        class Runner:
            def submit(self, name, job, *, on_complete):
                self.job, self.complete = job, on_complete
                return JobHandle("pending", lambda: None)

        page = ReportsPage(ReportsViewModel(), date(2026, 10, 11), job_runner=ImmediateJobRunner())
        self.addCleanup(page.deleteLater)
        page.refresh()
        runner = Runner()
        page._job_runner = runner
        self.assertTrue(page.refresh())
        self.assertTrue(page.editor.isReadOnly())
        QTest.qWait(200)
        self.assertFalse(page.load_progress.isHidden())
        self.assertTrue(page.previous_period_button.isEnabled())
        self.assertTrue(page.templates_button.isEnabled())
        self.assertTrue(page.copy_button.isEnabled())
        self.assertTrue(page.history_panel.search_line_edit.isReadOnly())
        self.assertTrue(page.ai_hint_line_edit.isReadOnly())
        QTest.mouseClick(page.next_period_button, Qt.MouseButton.LeftButton)
        QTest.mouseClick(page.report_type_control._buttons["monthly"], Qt.MouseButton.LeftButton)
        QTest.keyClicks(page.history_panel.search_line_edit, "query")
        QTest.keyClick(page.history_panel.sort_input, Qt.Key.Key_Down)
        QTest.keyClicks(page.editor, "draft")
        self.assertEqual(page._selected_day, date(2026, 10, 11))
        self.assertEqual(page._current_type(), "daily")
        self.assertEqual(page.history_panel.search_line_edit.text(), "")
        self.assertEqual(page.history_panel.sort_input.currentIndex(), 0)
        self.assertEqual(page.editor.toPlainText(), "Original daily")
        runner.complete(Result.failure(ValidationError("report_load_failed", "report_load_failed")))
        self.assertFalse(page.is_busy)
        self.assertFalse(page.editor.isReadOnly())
        self.assertTrue(page.load_progress.isHidden())
        self.assertFalse(page.history_panel.search_line_edit.isReadOnly())
        self.assertFalse(page.ai_hint_line_edit.isReadOnly())
        self.assertEqual(page.editor.toPlainText(), "Original daily")
        self.assertTrue(page.copy_button.isEnabled())
        self.assertTrue(page.previous_period_button.isEnabled())
        self.assertTrue(page.refresh())
        runner.complete(runner.job(CancellationToken()))
        QTest.qWait(200)
        self.assertTrue(page.copy_button.isEnabled())
        self.assertTrue(page.previous_period_button.isEnabled())

    def test_failed_background_submission_retains_draft_and_recovers_controls(self):
        class Model(ReportsViewModel):
            rewrite_available = True
        class ClosedRunner:
            def submit(self, *args, **kwargs):
                raise RuntimeError("job_runner_closed")
        page = ReportsPage(Model(), date(2026, 10, 10), job_runner=ImmediateJobRunner())
        self.addCleanup(page.deleteLater)
        page.refresh()
        page.editor.setPlainText("Unsaved draft")
        page._job_runner = ClosedRunner()
        with patch.object(QMessageBox, "warning"):
            page._rewrite_current()
            self.assertFalse(page.is_busy)
            self.assertFalse(page.editor.isReadOnly())
            self.assertEqual(page.editor.toPlainText(), "Unsaved draft")
            page._save_current()
            self.assertFalse(page.is_busy)
            self.assertEqual(page.editor.toPlainText(), "Unsaved draft")

    def test_loaded_report_formatting_does_not_create_false_unsaved_changes(self):
        for content in ("First\r\nSecond", "First\nSecond", "First\u2029Second", "Work\u00a0summary"):
            class Model(ReportsViewModel):
                def load(self, kind, day, content=content):
                    return Result.success(ReportEditorState(1, kind, day, day, content, saved=True, report_id=42))
            page = ReportsPage(Model(), date(2026, 5, 20), job_runner=ImmediateJobRunner())
            try:
                page.refresh()
                self.assertFalse(page.has_unsaved_changes)
                self.assertFalse(page.save_button.isEnabled())
                self.assertNotIn("Unsaved changes", page.report_state_label.text())
                self.assertEqual(page._states["daily"].content, content)
            finally:
                page.deleteLater()

    def test_report_identity_generation_and_export_follow_the_visible_draft(self):
        class Model(ReportsViewModel):
            fail_generation = False
            saved_content = ""

            def generate_draft(self, state):
                return (Result.failure(ValidationError("report_generate_failed", "report_generate_failed")) if self.fail_generation
                        else Result.success("Generated from current records"))

            def save(self, state, content):
                self.saved_content = content
                return Result.success(replace(state, content=content, saved=True, report_id=state.report_id or 42))

            def export_markdown(self, path, content):
                path.write_text(content, encoding="utf-8")
                return Result.success(path)

        model = Model()
        page = ReportsPage(model, date(2026, 5, 20), job_runner=ImmediateJobRunner())
        self.addCleanup(page.deleteLater)
        page.refresh()
        self.assertEqual(page.report_state_label.text(), "Generated draft")
        self.assertTrue(page.history_panel.export_button.isHidden())
        page.editor.setPlainText("Local changes")
        self.assertIn("Unsaved changes", page.report_state_label.text())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            page.generate_button.click()
        self.assertEqual(page.editor.toPlainText(), "Local changes")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            page.generate_button.click()
        self.assertEqual(page.editor.toPlainText(), "Generated from current records")
        page.save_button.click()
        self.assertEqual(page._states["daily"].report_id, 42)
        self.assertEqual(page.save_button.text(), "Save changes")
        self.assertFalse(page.save_button.isEnabled())
        page.editor.setPlainText("Visible unsaved draft")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "draft.md"
            with patch.object(QFileDialog, "getSaveFileName", return_value=(str(path), "")):
                page.export_current_button.export_requested.emit("current")
            self.assertEqual(path.read_text(encoding="utf-8"), "Visible unsaved draft")
            self.assertEqual(model.saved_content, "Generated from current records")
        model.fail_generation = True
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            page.generate_button.click()
        self.assertEqual(page.editor.toPlainText(), "Visible unsaved draft")
        self.assertEqual(page._states["daily"].report_id, 42)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            page.save_button.click()
        self.assertEqual(page._states["daily"].report_id, 42)
        self.assertFalse(page.has_unsaved_changes)

    def setUp(self) -> None:
        self.information = self.enterContext(patch.object(QMessageBox, "information"))
        self.warning = self.enterContext(patch.object(QMessageBox, "warning"))

    def test_cancelled_rewrite_preserves_draft_without_error_or_success_dialog(self):
        page = ReportsPage(ReportsViewModel(), date(2026, 4, 20), job_runner=ImmediateJobRunner())
        try:
            self.assertTrue(page.refresh())
            page.editor.setPlainText("Unsaved draft")
            page._set_rewrite_busy(True)
            page._complete_rewrite(Result.failure(CancellationError("ai_rewrite_cancelled", "ai_rewrite_cancelled")))
            self.assertEqual(page.editor.toPlainText(), "Unsaved draft")
            self.assertTrue(page.has_unsaved_changes)
            self.assertFalse(page.editor.isReadOnly())
            self.assertIsNone(page._last_error)
            self.warning.assert_not_called()
            self.information.assert_not_called()
        finally:
            page.editor.setPlainText("Original daily")
            page.deleteLater()

    def test_report_rewrite_uses_job_runner_instructions_and_protects_active_state(self) -> None:
        class ViewModel(ReportsViewModel):
            rewrite_available = True
            def rewrite(self, state, content, instructions, cancellation_token=None):
                self.arguments = (state, content, instructions)
                return Result.success("Rewritten text")

        class Runner:
            def submit(self, name, job, *, on_complete):
                self.name, self.job, self.complete = name, job, on_complete
                return JobHandle("pending", lambda: None)

        model, runner = ViewModel(), Runner()
        page = ReportsPage(model, date(2026, 4, 20), job_runner=runner)
        page.refresh()
        runner.complete(runner.job(CancellationToken()))
        page.ai_hint_line_edit.setText("Keep it concise")
        page._rewrite_current()
        self.assertEqual(runner.name, "rewrite_report")
        self.assertTrue(page.editor.isReadOnly())
        self.assertFalse(page.confirm_leave())
        self.assertFalse(page.previous_period_button.isEnabled())
        runner.complete(runner.job(CancellationToken()))
        self.assertEqual(model.arguments[2], "Keep it concise")
        self.assertEqual(page.editor.toPlainText(), "Rewritten text")
        self.assertTrue(page.has_unsaved_changes)
        self.assertFalse(page.editor.isReadOnly())
        page._complete_rewrite(Result.failure(ValidationError("ai_not_configured", "ai_not_configured")))
        self.assertEqual(page.editor.toPlainText(), "Rewritten text")

    def test_template_dialog_saves_resets_and_only_applies_saved_template(self) -> None:
        class Templates(ReportsViewModel):
            template = "Default template"
            def load_template(self, report_type):
                return Result.success(self.template)
            def save_template(self, report_type, text):
                self.template = text
                return Result.success()
            def reset_template(self, report_type):
                self.template = "Default template"
                return Result.success()

        model = Templates()
        dialog = ReportTemplateDialog(model, "daily")
        self.assertTrue(dialog.refresh())
        dialog.editor.setPlainText("Custom template")
        self.assertTrue(dialog.apply_button.isEnabled())
        applied = []
        dialog.apply_requested.connect(lambda: applied.append(True))
        dialog.apply_template()
        self.assertEqual(model.template, "Custom template")
        self.assertEqual(applied, [True])
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.assertTrue(dialog.reset_template())
        self.assertEqual(dialog.editor.toPlainText(), "Default template")

    def test_period_buttons_and_calendar_event_summary_are_connected(self) -> None:
        model = ReportsViewModel()
        page = ReportsPage(model, date(2026, 4, 20), job_runner=ImmediateJobRunner())
        page.refresh()
        page.next_period_button.click()
        self.assertEqual(page._selected_day, date(2026, 4, 21))
        page.previous_period_button.click()
        self.assertEqual(page._selected_day, date(2026, 4, 20))
        window = _window(MemoryWorkLogRepository())
        window.refresh()
        labels = window.calendar_page.records_widget.findChildren(QLabel)
        self.assertTrue(any("Planning" in label.text() for label in labels))
        self.assertTrue(window.entry_panel.time_tabs.tabBar().isVisibleTo(window.calendar_page))

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_report_type_cancel_preserves_draft_and_active_type(self) -> None:
        page = ReportsPage(ReportsViewModel(), date(2026, 4, 20), job_runner=ImmediateJobRunner(), confirm_discard=lambda: False)
        self.assertTrue(page.refresh())
        page.editor.setPlainText("Unsaved draft")
        page.report_type_control.set_value("weekly")
        self.assertEqual(page.report_type_control.value, "daily")
        self.assertEqual(page.editor.toPlainText(), "Unsaved draft")
        self.assertTrue(page.has_unsaved_changes)

    def test_history_and_refresh_cancel_preserve_report(self) -> None:
        page = ReportsPage(ReportsViewModel(), date(2026, 4, 20), job_runner=ImmediateJobRunner(), confirm_discard=lambda: False)
        page.refresh()
        page.editor.setPlainText("Unsaved draft")
        item = ReportHistoryDisplayItem(2, 1, "daily", date(2026, 4, 19), date(2026, 4, 19), "History", saved=True)
        page._select_history_item(item)
        self.assertFalse(page.refresh(date(2026, 4, 21)))
        self.assertEqual(page.editor.toPlainText(), "Unsaved draft")
        self.assertEqual(page._selected_day, date(2026, 4, 20))

    def test_saved_report_does_not_prompt_and_confirmed_discard_switches(self) -> None:
        prompts: list[bool] = []
        page = ReportsPage(ReportsViewModel(), date(2026, 4, 20), job_runner=ImmediateJobRunner(), confirm_discard=lambda: prompts.append(True) or True)
        page.refresh()
        page.editor.setPlainText("Saved draft")
        page._save_current()
        page.report_type_control.set_value("weekly")
        self.assertEqual(prompts, [])
        page.editor.setPlainText("Discard me")
        page.report_type_control.set_value("monthly")
        self.assertEqual(prompts, [True])
        self.assertEqual(page.editor.toPlainText(), "Original monthly")

    def test_shell_blocks_route_logout_and_close_for_unsaved_report(self) -> None:
        class Workflow:
            view_model = ReportsViewModel()

        window = _window(MemoryWorkLogRepository(), reports_workflow=Workflow())
        window.refresh()
        window._switch_route("reports")
        window.reports_page._confirm_discard = lambda: False
        window.reports_page.editor.setPlainText("Unsaved report")
        logged_out: list[bool] = []
        window.logout_requested.connect(lambda: logged_out.append(True))
        self.assertFalse(window._switch_route("calendar"))
        self.assertEqual(window.sidebar.active_route, "reports")
        window._request_logout()
        self.assertEqual(logged_out, [])
        window.show()
        self.assertFalse(window.close())
        self.assertEqual(window.reports_page.editor.toPlainText(), "Unsaved report")
        window.reports_page._confirm_discard = lambda: True
        window.close()

    def test_cancelled_navigation_preserves_both_entry_and_report_drafts(self) -> None:
        workflow = type("Workflow", (), {"view_model": ReportsViewModel()})()
        window = _window(MemoryWorkLogRepository(), reports_workflow=workflow)
        window.refresh()
        window.reports_page.editor.setPlainText("Unsaved report")
        window.reports_page._confirm_discard = lambda: True
        window._entry_dirty = True
        window._config = replace(window._config, confirm_discard_changes=lambda: False)
        self.assertFalse(window._switch_route("settings"))
        self.assertEqual(window.reports_page.editor.toPlainText(), "Unsaved report")
        self.assertTrue(window._entry_dirty)
        window._config = replace(window._config, confirm_discard_changes=lambda: True)
        window.reports_page._confirm_discard = lambda: False
        self.assertFalse(window._switch_route("settings"))
        self.assertEqual(window.reports_page.editor.toPlainText(), "Unsaved report")
        self.assertTrue(window._entry_dirty)
        window.reports_page._confirm_discard = lambda: True
        self.assertTrue(window.close())


if __name__ == "__main__":
    unittest.main()
