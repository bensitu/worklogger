from __future__ import annotations

from datetime import date
import unittest

from worklogger.domain.analytics.rules import (
    annual_chart_data,
    dashboard_data,
    analytics_period,
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
    def test_dashboard_uses_real_days_targets_modes_and_comparison(self) -> None:
        records = (
            _record(date(2026, 3, 6), "09:00", "17:00", 1.0, WorkType.NORMAL),
            _record(date(2026, 4, 6), "09:00", "19:00", 1.0, WorkType.NORMAL),
            _record(date(2026, 4, 7), "09:00", "18:00", 1.0, WorkType.REMOTE),
            _record(date(2026, 4, 8), None, None, 0.0, WorkType.PAID_LEAVE),
        )
        data = dashboard_data(records, year=2026, month=4, scope="monthly", standard_hours=7.5, monthly_target=120)
        self.assertEqual(data.total_days, 30)
        self.assertEqual(data.previous_total_days, 31)
        self.assertEqual(data.stats.work_days, 2)
        self.assertEqual(data.stats.total_hours, 17)
        self.assertEqual(data.stats.overtime_hours, 2)
        self.assertEqual(data.previous_stats.total_hours, 7)
        self.assertEqual(data.target_hours, 120)
        self.assertEqual(dict(data.work_modes), {"normal": 9, "remote": 8, "leave": 7.5})
        self.assertNotEqual(data.trend.bar_data, data.average.bar_data)
        self.assertEqual(data.daily_average_trend.bar_data[-1], ("04", 8.5))

    def test_dashboard_quarter_and_year_boundaries(self) -> None:
        self.assertEqual(analytics_period(2024, 2, "monthly"), (date(2024, 2, 1), date(2024, 2, 29)))
        data = dashboard_data((), year=2026, month=5, scope="quarterly", standard_hours=8, monthly_target=160)
        self.assertEqual((data.period_start, data.period_end), (date(2026, 4, 1), date(2026, 6, 30)))
        self.assertEqual(data.target_hours, 480)
        self.assertEqual(len(data.trend.bar_data), 3)
        data = dashboard_data((), year=2026, month=1, scope="annual", standard_hours=8, monthly_target=160)
        self.assertEqual(data.target_hours, 1920)
        self.assertEqual(data.previous_total_days, 365)
        self.assertEqual(len(data.trend.bar_data), 12)
        with self.assertRaises(ValueError):
            analytics_period(2026, 1, "invalid")

    def test_report_periods_match_baseline_week_and_month_boundaries(self) -> None:
        weekly = weekly_period(date(2026, 4, 22))
        self.assertEqual(weekly.start, date(2026, 4, 20))
        self.assertEqual(weekly.end, date(2026, 4, 26))

        monthly = monthly_period(2026, 2)
        self.assertEqual(monthly.start, date(2026, 2, 1))
        self.assertEqual(monthly.end, date(2026, 2, 28))

        with self.assertRaises(ValueError):
            validate_report_period("weekly", date(2026, 4, 2), date(2026, 4, 1))

    def test_daily_average_quarters_use_work_days_across_the_selected_year(self) -> None:
        records = (
            _record(date(2026, 1, 5), "09:00", "17:00", 0, WorkType.NORMAL),
            _record(date(2026, 1, 6), "09:00", "17:00", 0, WorkType.REMOTE),
            _record(date(2026, 2, 5), "06:00", "20:00", 0, WorkType.NORMAL),
            _record(date(2026, 3, 5), None, None, 0, WorkType.PAID_LEAVE),
            _record(date(2026, 3, 6), None, None, 0, WorkType.NORMAL),
            _record(date(2026, 7, 5), "09:00", "15:00", 0, WorkType.NORMAL),
            _record(date(2026, 12, 5), "09:00", "19:00", 0, WorkType.NORMAL),
            _record(date(2025, 1, 5), "06:00", "21:00", 0, WorkType.NORMAL),
            _record(date(2027, 1, 5), "06:00", "21:00", 0, WorkType.NORMAL),
        )
        for month in (1, 5, 12):
            data = dashboard_data(records, year=2026, month=month, scope="quarterly", standard_hours=8, monthly_target=168)
            expected = (("Q1", 10), ("Q2", 0), ("Q3", 6), ("Q4", 10))
            self.assertEqual(data.daily_average_trend.bar_data, expected)
            self.assertEqual(data.daily_average_trend.line_data, expected)
            self.assertFalse(data.daily_average_trend.leave_indices)

    def test_daily_average_annual_scope_includes_all_twelve_months(self) -> None:
        records = (
            _record(date(2026, 1, 5), "09:00", "17:00", 0, WorkType.NORMAL),
            _record(date(2026, 1, 6), "08:00", "20:00", 0, WorkType.NORMAL),
            _record(date(2026, 6, 5), "09:00", "15:00", 0, WorkType.NORMAL),
            _record(date(2026, 12, 5), "09:00", "16:00", 0, WorkType.NORMAL),
            _record(date(2026, 12, 6), None, None, 0, WorkType.PAID_LEAVE),
            _record(date(2025, 1, 5), "06:00", "21:00", 0, WorkType.NORMAL),
        )
        data = dashboard_data(records, year=2026, month=5, scope="annual", standard_hours=8, monthly_target=168)
        expected = tuple((f"{month:02d}", {1: 10, 6: 6, 12: 7}.get(month, 0)) for month in range(1, 13))
        self.assertEqual(data.daily_average_trend.bar_data, expected)
        self.assertEqual(data.daily_average_trend.line_data, expected)

    def test_daily_average_monthly_scope_keeps_six_months_across_year_boundary(self) -> None:
        records = tuple(
            _record(day, "09:00", end, 0, WorkType.NORMAL)
            for day, end in ((date(2025, 8, 5), "20:00"), (date(2025, 12, 5), "14:00"),
                             (date(2026, 1, 5), "16:00"), (date(2026, 2, 5), "19:00"),
                             (date(2026, 3, 5), "20:00"))
        )
        data = dashboard_data(records, year=2026, month=2, scope="monthly", standard_hours=8, monthly_target=168)
        self.assertEqual(data.daily_average_trend.line_data,
                         (("09", 0), ("10", 0), ("11", 0), ("12", 5), ("01", 7), ("02", 10)))

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
