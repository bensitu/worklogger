from dataclasses import replace
from datetime import date, timedelta
import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import qInstallMessageHandler
from PySide6.QtWidgets import QApplication, QScrollArea

from worklogger.domain.analytics.models import ChartDataBundle
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkLog, WorkType
from worklogger.infrastructure.i18n import available_languages, set_language
from worklogger.presentation.date_labels import duration_label, period_range_label
from worklogger.presentation.shell.pages import _month_chart_labels, _period_label
from worklogger.presentation.viewmodels.reports import ReportEditorState
from worklogger.presentation.widgets.combo_chart import chart_tick_step
from worklogger.presentation.widgets.report_history import ReportHistoryDisplayItem
from worklogger.presentation.widgets.segmented_control import SegmentedControl
from tests.presentation.test_ui_layout import sample_window
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


class CalendarReportsAnalyticsLayoutTests(unittest.TestCase):
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

    def test_duration_rounding_and_localized_periods(self):
        set_language("en_US")
        for hours, label in ((186.75, "186h 45m"), (1.999, "2h 0m"), (-0.25, "-0h 15m"), (0, "0h 0m")):
            self.assertEqual(duration_label(hours), label)
        self.assertEqual(period_range_label(date(2026, 5, 18), date(2026, 5, 24)), "May 18 - May 24, 2026")
        self.assertEqual(period_range_label(date(2025, 12, 29), date(2026, 1, 4)), "December 29, 2025 - January 4, 2026")
        self.assertIn("Week 1", _period_label(ReportEditorState(1, "weekly", date(2025, 12, 29), date(2026, 1, 4), "")))

    def test_chart_labels_preserve_values_and_stacking(self):
        bundle = ChartDataBundle((("12", 8.5), ("01", 7.25)), (("12", 8.5), ("01", 7.25)), frozenset({1}), (None, 8), (("01", 8),))
        result = _month_chart_labels(bundle)
        self.assertEqual(result.bar_data, (("December", 8.5), ("January", 7.25)))
        self.assertEqual(result.leave_hours_data, (("January", 8),))
        self.assertEqual(result.leave_indices, bundle.leave_indices)
        self.assertEqual(bundle.bar_data[0][0], "12")
        for maximum in (0, 8, 10, 40, 59.5, 4000):
            self.assertGreaterEqual(chart_tick_step(maximum) * 4, maximum)

    def test_segment_selection_is_visibly_checked_and_signals_once(self):
        control = SegmentedControl((("first", "First"), ("second", "Second")), tabs=True)
        changed = []
        control.value_changed.connect(changed.append)
        self.assertTrue(control._buttons["first"].isChecked())
        control._buttons["second"].click()
        control._buttons["second"].click()
        self.assertEqual(changed, ["second"])
        self.assertTrue(control._buttons["second"].isChecked())
        self.assertFalse(control._buttons["first"].isChecked())

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
                for dark in (False, True):
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
                        for width, height in ((880, 580), (1100, 700)):
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
