from dataclasses import replace
from datetime import date, timedelta
import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import qInstallMessageHandler
from PySide6.QtWidgets import QApplication, QScrollArea

from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkLog, WorkType
from worklogger.infrastructure.i18n import available_languages, set_language
from worklogger.presentation.viewmodels.reports import ReportEditorState
from worklogger.presentation.widgets.report_history import ReportHistoryDisplayItem
from tests.visual.shell_checks import sample_window
from tests.presentation.test_shell_pages import ReportsViewModel


class WeeklyReports(ReportsViewModel):
    def load(self, report_type, day):
        start = day - timedelta(days=day.weekday()) if report_type == "weekly" else day
        end = start + timedelta(days=6) if report_type == "weekly" else day
        return Result.success(ReportEditorState(1, report_type, start, end,
            "# Weekly Summary\n\n## Key Achievements\n- Implemented calendar updates.\n\n"
            "## Challenges & Solutions\n- Verified layout at different display scales.\n\n"
            "## Plan for Next Week\n- Complete regression testing.", saved=True, report_id=1))

    def list_history(self, report_type):
        return Result.success(tuple(ReportHistoryDisplayItem(index, 1, report_type, start,
            start + timedelta(days=6), "", "Saved report", index == 1)
            for index, start in enumerate((date(2026, 5, 18), date(2026, 5, 11), date(2026, 5, 4),
                date(2026, 4, 27), date(2026, 4, 20)), 1)))


class ReportingLayoutChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        set_language("en_US")

    def capture(self, widget, name, language):
        directory = os.environ.get("WORKLOGGER_SCREENSHOTS")
        if directory:
            path = Path(directory)
            path.mkdir(parents=True, exist_ok=True)
            self.assertTrue(widget.grab().save(str(path / f"{language}-{name}.png")))

    def test_calendar_cells_do_not_stretch_with_tall_window(self):
        window = sample_window()
        window.show()
        try:
            window.resize(1100, 950)
            self.assertTrue(window.refresh())
            self.app.processEvents()
            cells = [button for button in window.calendar_view.day_buttons() if button.isVisible()]
            self.assertTrue(cells)
            for button in cells:
                self.assertLessEqual(button.height(), button.width() * 1.25)
            self.assertLess(window.calendar_view.grid_frame.height(), window.calendar_view.height() - 50)
        finally:
            window.close()

    def test_filled_reports_and_analytics_fit_all_languages(self):
        warnings = []
        previous = qInstallMessageHandler(lambda kind, context, message: warnings.append(message))
        try:
            for language in available_languages():
                set_language(language)
                for dark in ((False, True) if language == "en_US" else (language in ("ja_JP", "zh_TW"),)):
                    window = sample_window()
                    window.reports_page._view_model = WeeklyReports()
                    window._config = replace(window._config, dark=dark)
                    records = window.analytics_page._view_model._dashboard_handler._repository
                    for day, mode in ((5, WorkType.REMOTE), (12, WorkType.BUSINESS_TRIP), (19, WorkType.PAID_LEAVE), (20, WorkType.NORMAL)):
                        records.save(WorkLog(1, date(2026, 5, day), "09:00", "18:30", 1, "Test record", mode))
                    window.apply_theme()
                    window.refresh()
                    window.show()
                    try:
                        sizes = ((880, 580), (1100, 700)) if language == "en_US" else ((880, 580),)
                        for width, height in sizes:
                            window.resize(width, height)
                            for route in ("reports", "analytics"):
                                self.assertTrue(window._switch_route(route))
                                page = window.page_stack.currentWidget()
                                self.assertTrue(page.refresh(date(2026, 5, 21)))
                                if route == "reports":
                                    page.report_type_control.set_value("weekly")
                                self.app.processEvents()
                                self.assertEqual((window.width(), window.height()), (width, height))
                                for scroll in page.findChildren(QScrollArea):
                                    self.assertEqual(scroll.horizontalScrollBar().maximum(), 0, (language, route, width))
                                if route == "reports":
                                    button = page.history_panel._buttons[0]
                                    self.assertTrue(button.property("active"))
                                    self.assertIn("\n", button.text())
                                    self.assertLessEqual(button._document.size().height(), button.height() - 20)
                                    page.history_panel.search_line_edit.setText("11")
                                    self.assertEqual(len(page.history_panel._buttons), 1)
                                    page.history_panel.search_line_edit.clear()
                                    self.app.processEvents()
                                    self.assertTrue(all(button.isVisible() for button in page.history_panel._buttons.values()))
                                    buttons = tuple(page.history_panel._buttons.values())
                                    for first, second in zip(buttons, buttons[1:]):
                                        self.assertLess(first.geometry().bottom(), second.geometry().top())
                                    for button in buttons:
                                        self.assertLessEqual(button._document.size().height(), button.height() - 20)
                                else:
                                    self.assertEqual(page._summary_grid.itemAtPosition(0, 0).widget(), page.monthly_hours_card)
                                    self.assertIsNotNone(page._summary_grid.itemAtPosition(1, 0) if width == 880 else page._summary_grid.itemAtPosition(0, 3))
                                    self.assertEqual(len(page.breakdown_chart.chart._segments), 4)
                                    self.assertEqual(page.breakdown_chart.chart._keys, ("normal", "remote", "business_trip", "leave"))
                                self.capture(window, f"filled-{route}-{'dark' if dark else 'light'}-{width}", language)
                    finally:
                        window.close()
            self.assertFalse([message for message in warnings if "QFont::" in message or "QPainter::" in message or "QSvg" in message], warnings)
        finally:
            qInstallMessageHandler(previous)
