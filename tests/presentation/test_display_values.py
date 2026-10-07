"""Duration formatting and chart labels without rendering a window."""

from datetime import date
import unittest

from worklogger.domain.analytics.models import ChartDataBundle
from worklogger.infrastructure.i18n import set_language
from worklogger.presentation.date_labels import duration_label, period_range_label
from worklogger.presentation.shell.analytics_page import _month_chart_labels
from worklogger.presentation.shell.reports_page import _period_label
from worklogger.presentation.viewmodels.reports import ReportEditorState
from worklogger.presentation.widgets.combo_chart import chart_tick_step


class DisplayValueTests(unittest.TestCase):
    def setUp(self):
        set_language("en_US")

    def tearDown(self):
        set_language("en_US")

    def test_duration_rounding_and_period_boundaries(self):
        for hours, label in ((186.75, "186h 45m"), (1.999, "2h 0m"), (-0.25, "-0h 15m"), (0, "0h 0m")):
            self.assertEqual(duration_label(hours), label)
        self.assertEqual(period_range_label(date(2026, 5, 18), date(2026, 5, 24)), "May 18 - May 24, 2026")
        self.assertEqual(period_range_label(date(2025, 12, 29), date(2026, 1, 4)), "December 29, 2025 - January 4, 2026")
        self.assertIn("Week 1", _period_label(ReportEditorState(1, "weekly", date(2025, 12, 29), date(2026, 1, 4), "")))

    def test_chart_labels_preserve_values_and_scale(self):
        bundle = ChartDataBundle((("12", 8.5), ("01", 7.25)), (("12", 8.5), ("01", 7.25)), frozenset({1}), (None, 8), (("01", 8),))
        result = _month_chart_labels(bundle)
        self.assertEqual(result.bar_data, (("December", 8.5), ("January", 7.25)))
        self.assertEqual(result.leave_hours_data, (("January", 8),))
        self.assertEqual(result.leave_indices, bundle.leave_indices)
        self.assertEqual(bundle.bar_data[0][0], "12")
        for maximum in (0, 8, 10, 40, 59.5, 4000):
            self.assertGreaterEqual(chart_tick_step(maximum) * 4, maximum)


if __name__ == "__main__":
    unittest.main()
