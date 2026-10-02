from __future__ import annotations

from dataclasses import replace
from datetime import date
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox, QLabel

from worklogger.domain.shared.result import Result
from worklogger.domain.shared.errors import ValidationError
from worklogger.app.job_runner import JobHandle, CancellationToken
from worklogger.presentation.reporting.dialog import ReportTemplateDialog
from worklogger.presentation.job_runner import ImmediateJobRunner
from worklogger.presentation.shell.pages import AnalyticsPage
from worklogger.presentation.viewmodels import SettingsState
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

    def list_history(self, report_type: str):
        return Result.success(())

    def save(self, state: ReportEditorState, content: str):
        return Result.success(replace(state, content=content, saved=True))


class ShellPagesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.information = self.enterContext(patch.object(QMessageBox, "information"))
        self.warning = self.enterContext(patch.object(QMessageBox, "warning"))

    def test_report_rewrite_uses_job_runner_instructions_and_protects_active_state(self) -> None:
        class ViewModel(ReportsViewModel):
            rewrite_available = True
            def rewrite(self, state, content, instructions):
                self.arguments = (state, content, instructions)
                return Result.success("Rewritten text")

        class Runner:
            def submit(self, name, job, *, on_complete):
                self.name, self.job, self.complete = name, job, on_complete
                return JobHandle("pending", lambda: None)

        model, runner = ViewModel(), Runner()
        page = ReportsPage(model, date(2026, 4, 20), job_runner=runner)
        page.refresh()
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
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertTrue(dialog.save_template())
        self.assertEqual(model.template, "Custom template")
        applied = []
        dialog.apply_requested.connect(lambda: applied.append(True))
        dialog.apply_template()
        self.assertEqual(applied, [True])
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.assertTrue(dialog.reset_template())
        self.assertEqual(dialog.editor.toPlainText(), "Default template")

    def test_period_buttons_and_calendar_event_summary_are_connected(self) -> None:
        model = ReportsViewModel()
        page = ReportsPage(model, date(2026, 4, 20))
        page.refresh()
        page.next_period_button.click()
        self.assertEqual(page._selected_day, date(2026, 4, 21))
        page.previous_period_button.click()
        self.assertEqual(page._selected_day, date(2026, 4, 20))
        window = _window(MemoryWorkLogRepository())
        window.refresh()
        labels = window.calendar_page.records_widget.findChildren(QLabel)
        self.assertTrue(any("Planning" in label.text() for label in labels))
        self.assertTrue(window.entry_panel.time_tabs.tabBar().isVisibleTo(window.entry_panel))

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_report_type_cancel_preserves_draft_and_active_type(self) -> None:
        page = ReportsPage(ReportsViewModel(), date(2026, 4, 20), confirm_discard=lambda: False)
        self.assertTrue(page.refresh())
        page.editor.setPlainText("Unsaved draft")
        page.report_type_control.set_value("weekly")
        self.assertEqual(page.report_type_control.value, "daily")
        self.assertEqual(page.editor.toPlainText(), "Unsaved draft")
        self.assertTrue(page.has_unsaved_changes)

    def test_history_and_refresh_cancel_preserve_report(self) -> None:
        page = ReportsPage(ReportsViewModel(), date(2026, 4, 20), confirm_discard=lambda: False)
        page.refresh()
        page.editor.setPlainText("Unsaved draft")
        item = ReportHistoryDisplayItem(2, 1, "daily", date(2026, 4, 19), date(2026, 4, 19), "History", "Saved")
        page._select_history_item(item)
        self.assertFalse(page.refresh(date(2026, 4, 21)))
        self.assertEqual(page.editor.toPlainText(), "Unsaved draft")
        self.assertEqual(page._selected_day, date(2026, 4, 20))

    def test_saved_report_does_not_prompt_and_confirmed_discard_switches(self) -> None:
        prompts: list[bool] = []
        page = ReportsPage(ReportsViewModel(), date(2026, 4, 20), confirm_discard=lambda: prompts.append(True) or True)
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
