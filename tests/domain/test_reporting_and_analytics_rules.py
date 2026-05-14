from __future__ import annotations

from datetime import date
import unittest

from worklogger.domain.analytics.rules import (
    annual_chart_data,
    month_stats,
    monthly_chart_data,
    quarterly_chart_data,
)
from worklogger.domain.reporting.periods import (
    monthly_period,
    validate_report_period,
    weekly_period,
)
from worklogger.domain.worklog.models import WorkLog, WorkType
from worklogger.domain.worklog.rules import normalize_work_log


def _record(
    day: date,
    start: str | None,
    end: str | None,
    break_hours: float,
    work_type: WorkType,
) -> WorkLog:
    return normalize_work_log(
        WorkLog(
            user_id=1,
            day=day,
            start_time=start,
            end_time=end,
            break_hours=break_hours,
            work_type=work_type,
        )
    )


class ReportingAndAnalyticsRuleTests(unittest.TestCase):
    def test_report_periods_match_baseline_week_and_month_boundaries(self) -> None:
        weekly = weekly_period(date(2026, 4, 22))
        self.assertEqual(weekly.start, date(2026, 4, 20))
        self.assertEqual(weekly.end, date(2026, 4, 26))

        monthly = monthly_period(2026, 2)
        self.assertEqual(monthly.start, date(2026, 2, 1))
        self.assertEqual(monthly.end, date(2026, 2, 28))

        with self.assertRaises(ValueError):
            validate_report_period("weekly", date(2026, 4, 2), date(2026, 4, 1))

    def test_month_stats_excludes_leave_from_work_and_overtime(self) -> None:
        records = (
            _record(date(2026, 4, 6), "09:00", "19:00", 1.0, WorkType.COMP_LEAVE),
            _record(date(2026, 4, 7), "09:00", "18:00", 1.0, WorkType.NORMAL),
        )
        stats = month_stats(records, 8.0)
        self.assertEqual(stats.total_hours, 8.0)
        self.assertEqual(stats.overtime_hours, 0.0)
        self.assertEqual(stats.work_days, 1)
        self.assertEqual(stats.leave_days, 1)
        self.assertEqual(stats.average_hours, 8.0)

    def test_chart_bundle_preserves_leave_overlay_average_semantics(self) -> None:
        records = {
            date(2026, 4, 6): _record(date(2026, 4, 6), None, None, 0.0, WorkType.PAID_LEAVE),
            date(2026, 4, 7): _record(date(2026, 4, 7), "09:00", "13:00", 0.0, WorkType.COMP_LEAVE),
            date(2026, 4, 8): _record(date(2026, 4, 8), "09:00", "18:00", 1.0, WorkType.NORMAL),
        }
        bundle = monthly_chart_data(
            date(2026, 4, 1),
            date(2026, 4, 30),
            "average",
            True,
            records.get,
            standard_leave_hours=8.0,
        )
        self.assertEqual(bundle.bar_data[1], ("W2", 8.0))
        self.assertEqual(bundle.leave_indices, frozenset({1}))
        self.assertEqual(bundle.leave_line_data[1], 6.0)
        self.assertEqual(bundle.leave_hours_data[1], ("W2", 6.0))

    def test_quarterly_and_annual_data_are_pure_domain_preparation(self) -> None:
        by_month = {
            1: (
                _record(date(2026, 1, 5), None, None, 0.0, WorkType.PAID_LEAVE),
                _record(date(2026, 1, 6), "09:00", "13:00", 0.0, WorkType.COMP_LEAVE),
            ),
            4: (
                _record(date(2026, 4, 6), None, None, 0.0, WorkType.PAID_LEAVE),
                _record(date(2026, 4, 13), "09:00", "13:00", 0.0, WorkType.COMP_LEAVE),
            ),
        }

        quarterly = quarterly_chart_data(
            lambda month: by_month.get(month, ()),
            2026,
            "average",
            True,
            standard_leave_hours=8.0,
        )
        annual = annual_chart_data(
            lambda month: by_month.get(month, ()),
            2026,
            tuple(f"M{month}" for month in range(1, 13)),
            "average",
            True,
            standard_leave_hours=8.0,
        )

        self.assertEqual(quarterly.leave_line_data[1], 6.0)
        self.assertEqual(annual.leave_hours_data[0], ("M1", 6.0))


if __name__ == "__main__":
    unittest.main()
