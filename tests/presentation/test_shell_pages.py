from __future__ import annotations

from dataclasses import replace
from datetime import date
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from worklogger.domain.shared.result import Result
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


if __name__ == "__main__":
    unittest.main()
