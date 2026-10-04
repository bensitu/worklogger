"""Progress values, period labels, and accessible chart descriptions."""

from dataclasses import replace
from datetime import date
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from tests.presentation.test_analytics_presentation import MemoryWorkLogRepository
from worklogger.app.use_cases.analytics import GetAnalyticsBundleHandler, GetAnalyticsDashboardHandler
from worklogger.infrastructure.export import AnalyticsCsvExporter, AnalyticsPdfExporter
from worklogger.infrastructure.i18n import _, set_language
from worklogger.presentation.shell.pages import AnalyticsPage
from worklogger.presentation.viewmodels import AnalyticsViewModel
from worklogger.presentation.widgets.progress_cards import DonutGauge, OvertimeComparisonChart


class ProgressCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        set_language("en_US")

    def test_percentage_preserves_values_above_target(self):
        gauge = DonutGauge()
        self.addCleanup(gauge.deleteLater)
        for progress, expected in ((0, "0%"), (0.75, "75%"), (1, "100%"),
                                   (213.5 / 168, "127%"), (526 / 504, "104%"),
                                   (2, "200%"), (2.5, "250%"), (10, "1000%"),
                                   (-1, "0%"), (float("nan"), "0%"), (float("inf"), "0%")):
            with self.subTest(progress=progress):
                gauge.set_progress(progress)
                self.assertEqual(gauge.percentage_text, expected)
                self.assertEqual(gauge.accessibleName(), expected)

    def test_period_titles_and_zero_target(self):
        records = MemoryWorkLogRepository()
        page = AnalyticsPage(AnalyticsViewModel(
            user_id=1, bundle_handler=GetAnalyticsBundleHandler(records),
            dashboard_handler=GetAnalyticsDashboardHandler(records),
            csv_exporter=AnalyticsCsvExporter(), pdf_exporter=AnalyticsPdfExporter(),
        ), date(2026, 4, 21))
        self.addCleanup(page.deleteLater)
        for language in ("en_US", "zh_CN"):
            set_language(language)
            for scope, title in (("monthly", "Monthly Hours"), ("quarterly", "Quarterly Hours"),
                                 ("annual", "Annual Hours")):
                page.scope_control.set_value(scope)
                self.assertTrue(page.refresh(date(2026, 4, 21)))
                self.assertEqual(page.monthly_hours_card.title_label.text(), _(title))
            state = replace(page._dashboard, target_hours=168,
                            stats=replace(page._dashboard.stats, total_hours=213.5))
            page._set_state(state)
            self.assertEqual(page.monthly_hours_card.gauge.percentage_text, "127%")
            page._set_state(replace(state, target_hours=0))
            self.assertEqual(page.monthly_hours_card.gauge.percentage_text, "0%")

    def test_overtime_comparison_exposes_both_periods_accessibly(self):
        chart = OvertimeComparisonChart()
        self.addCleanup(chart.deleteLater)
        for language in ("en_US", "ja_JP"):
            set_language(language)
            for current, previous in ((70.5, 20), (0, 0)):
                chart.set_hours(current, previous)
                expected = _("Overtime comparison: previous period {previous:.1f}h, current period {current:.1f}h").format(
                    previous=previous, current=current)
                self.assertEqual(chart.toolTip(), expected)
                self.assertIn(f"{previous:.1f}h", chart.toolTip())
                self.assertIn(f"{current:.1f}h", chart.toolTip())
                self.assertEqual(chart.toolTip(), chart.accessibleName())


if __name__ == "__main__":
    unittest.main()
