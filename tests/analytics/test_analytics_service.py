import os
import sys
import unittest
from datetime import date


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_ROOT = os.path.join(PROJECT_ROOT, "worklogger")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from core.models import WorkRecord
from services.analytics_service import (
    annual_chart_data_v3,
    export_chart_csv,
    month_stats,
    monthly_chart_data_v3,
    quarterly_chart_data_v3,
)


class AnalyticsServiceTests(unittest.TestCase):
    def test_v3_metric_and_leave_bundle(self):
        records = {
            "2026-04-01": WorkRecord("2026-04-01", "09:00", "18:00", 1.0, "", "normal", 0),
            "2026-04-02": WorkRecord("2026-04-02", "09:00", "17:00", 1.0, "", "remote", 0),
            "2026-04-06": WorkRecord("2026-04-06", "", "", 0.0, "", "paid_leave", 0),
        }

        bundle = monthly_chart_data_v3(
            date(2026, 4, 1),
            date(2026, 4, 30),
            "average",
            True,
            record_getter=records.get,
            standard_hours=8.0,
        )

        self.assertEqual(bundle.bar_data[0], ("W1", 7.5))
        self.assertEqual(bundle.line_data[0], ("W1", 7.5))
        self.assertEqual(bundle.leave_indices, {1})
        self.assertEqual(bundle.leave_line_data[1], 8.0)
        self.assertEqual(bundle.leave_hours_data[1], ("W2", 8.0))

    def test_v3_average_metric_averages_monthly_leave_hours(self):
        records = {
            "2026-04-06": WorkRecord("2026-04-06", "", "", 0.0, "", "paid_leave", 0),
            "2026-04-07": WorkRecord("2026-04-07", "09:00", "13:00", 0.0, "", "comp_leave", 0),
        }

        bundle = monthly_chart_data_v3(
            date(2026, 4, 1),
            date(2026, 4, 30),
            "average",
            True,
            record_getter=records.get,
            standard_hours=8.0,
        )

        self.assertEqual(bundle.leave_indices, {1})
        self.assertEqual(bundle.leave_line_data[1], 6.0)
        self.assertEqual(bundle.leave_hours_data[1], ("W2", 6.0))

    def test_v3_average_metric_averages_quarterly_and_annual_leave_hours(self):
        records_by_month = {
            "2026-01": [
                WorkRecord("2026-01-05", "", "", 0.0, "", "paid_leave", 0),
                WorkRecord("2026-01-06", "09:00", "13:00", 0.0, "", "comp_leave", 0),
            ],
            "2026-04": [
                WorkRecord("2026-04-06", "", "", 0.0, "", "paid_leave", 0),
                WorkRecord("2026-04-13", "09:00", "13:00", 0.0, "", "comp_leave", 0),
            ],
        }

        def month_records(month: str):
            return records_by_month.get(month, [])

        quarterly = quarterly_chart_data_v3(
            month_records,
            2026,
            "average",
            True,
            standard_hours=8.0,
        )
        annual = annual_chart_data_v3(
            month_records,
            2026,
            ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
            "average",
            True,
            standard_hours=8.0,
        )

        self.assertEqual(quarterly.leave_line_data[1], 6.0)
        self.assertEqual(quarterly.leave_hours_data[1], ("Q2", 6.0))
        self.assertEqual(annual.leave_line_data[0], 6.0)
        self.assertEqual(annual.leave_hours_data[0], ("Jan", 6.0))

    def test_leave_with_times_is_not_work_or_overtime(self):
        records = {
            "2026-04-06": WorkRecord("2026-04-06", "09:00", "19:00", 1.0, "", "comp_leave", 0),
            "2026-04-07": WorkRecord("2026-04-07", "09:00", "18:00", 1.0, "", "normal", 0),
        }

        total, overtime, work_days, leave_days, average = month_stats(
            list(records.values()),
            8.0,
        )
        self.assertEqual(total, 8.0)
        self.assertEqual(overtime, 0.0)
        self.assertEqual(work_days, 1)
        self.assertEqual(leave_days, 1)
        self.assertEqual(average, 8.0)

        bundle = monthly_chart_data_v3(
            date(2026, 4, 1),
            date(2026, 4, 30),
            "hours",
            True,
            record_getter=records.get,
            standard_hours=8.0,
        )
        self.assertEqual(bundle.bar_data[1], ("W2", 8.0))
        self.assertEqual(bundle.leave_hours_data[1], ("W2", 9.0))
        self.assertEqual(bundle.leave_line_data[1], 9.0)

    def test_export_chart_csv_adds_leave_hours(self):
        import tempfile

        records = {
            "2026-04-06": WorkRecord("2026-04-06", "", "", 0.0, "", "paid_leave", 0),
        }
        bundle = monthly_chart_data_v3(
            date(2026, 4, 1),
            date(2026, 4, 30),
            "hours",
            True,
            record_getter=records.get,
            standard_hours=8.0,
        )

        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as fp:
            path = fp.name
        try:
            export_chart_csv(path, bundle, "Period", "Work hours (h)", "Leave Hours (h)")
            with open(path, encoding="utf-8-sig") as fp:
                text = fp.read()
            self.assertIn("Period,Work hours (h),Leave Hours (h)", text)
            self.assertIn("W2,0.00,8.00", text)
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()

