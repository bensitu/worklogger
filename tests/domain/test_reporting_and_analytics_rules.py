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
    period_for_day,
    shift_report_period,
    validate_report_period,
    weekly_period,
)
from worklogger.domain.worklog.models import CustomEntryType, WorkLog, EntryType, WorkMode
from worklogger.domain.shared.dates import add_months
from worklogger.domain.worklog.rules import aggregate_days, normalize_work_log
from worklogger.domain.settings.work_schedule import WorkSchedule
from worklogger.domain.settings.validation import normalize_setting
from worklogger.config.constants import WORK_SCHEDULE_SETTING_KEY


def _record(
    day: date,
    start: str | None,
    end: str | None,
    break_hours: float,
    entry_type: EntryType,
) -> WorkLog:
    return normalize_work_log(
        WorkLog(
            user_id=1,
            day=day,
            start_time=start,
            end_time=end,
            break_hours=break_hours,
            entry_type=entry_type,
        )
    )


class ReportingAndAnalyticsRuleTests(unittest.TestCase):
    def test_weekly_plans_count_leap_months_and_preserve_actual_attendance(self):
        start, end = date(2024, 2, 1), date(2024, 2, 29)
        for mode, expected in (("full_month", 29), ("one_day_off", 25),
                               ("two_days_off", 21), ("two_and_a_half_days_off", 19)):
            plan = WorkSchedule.preset(mode)
            self.assertEqual(plan.planned_days(start, end), expected)
            self.assertEqual(WorkSchedule.decode(normalize_setting(WORK_SCHEDULE_SETTING_KEY, plan.encode())), plan)
        custom = WorkSchedule("custom", (0.5, 1, 0, 1, 0, 1, 0))
        self.assertEqual(custom.planned_days(date(2026, 10, 12), date(2026, 10, 18)), 3.5)
        self.assertEqual(WorkSchedule.preset("two_days_off").planned_days(date(2024, 1, 1), date(2024, 12, 31)), 262)
        rows = (_record(date(2024, 2, 3), "09:00", "10:00", 0, EntryType.NORMAL),)
        data = dashboard_data(rows, year=2024, month=2, scope="monthly", standard_hours=8,
                              monthly_target=168, work_schedule=WorkSchedule.preset("two_and_a_half_days_off"))
        self.assertEqual((data.stats.work_days, data.planned_work_days, data.target_hours), (1, 19, 168))
        self.assertEqual(data.trend.bar_data[0][0], "W1\n2/1-3")
        monday = monthly_chart_data(start, end, "hours", False, lambda _day: None, week_start_monday=True)
        self.assertEqual(monday.bar_data[0][0], "W1\n2/1-4")
        self.assertEqual(monday.bar_data[-1][0], "W5\n2/26-29")

    def test_invalid_weekly_plans_are_rejected_and_missing_preferences_use_calendar_days(self):
        for value in ('{}', 'null', '{"mode":"custom","days":[1]}',
                      '{"mode":"one_day_off","days":[1,1,1,1,1,1,1]}',
                      '{"mode":"custom","days":[true,1,1,1,1,0,0]}'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "work_schedule_invalid"):
                normalize_setting(WORK_SCHEDULE_SETTING_KEY, value)
            self.assertEqual(WorkSchedule.from_setting(value), WorkSchedule())
        self.assertEqual(WorkSchedule.from_setting(None).planned_days(date.min, date.min), 1)
        self.assertEqual(WorkSchedule().planned_days(date.max, date.max), 1)

    def test_dashboard_handles_the_supported_date_boundaries(self):
        for day in (date.min, date.max):
            for scope in ("monthly", "quarterly", "annual"):
                value = dashboard_data((), year=day.year, month=day.month, scope=scope,
                                       standard_hours=8, monthly_target=168)
                self.assertEqual(value.stats.total_hours, 0)
                self.assertGreaterEqual(value.previous_total_days, 0)

    def test_period_selection_handles_leap_months_and_rejects_unrepresentable_weeks(self):
        for day in (date(2024, 2, 29), date(9999, 12, 31)):
            period = period_for_day("monthly", day)
            self.assertEqual(period, monthly_period(day.year, day.month))
            self.assertEqual(period_for_day("daily", day).end, day)
        for day, monday in ((date.min, False), (date.max, True)):
            with self.assertRaisesRegex(ValueError, "report_period_invalid"):
                period_for_day("weekly", day, monday)
        self.assertEqual(shift_report_period(date(2024, 1, 31), "monthly", 1), date(2024, 2, 29))
        self.assertEqual(shift_report_period(date(2026, 1, 31), "monthly", 1), date(2026, 2, 28))
        self.assertEqual(shift_report_period(date(2026, 12, 28), "weekly", 1), date(2027, 1, 4))
        for report_type in ("daily", "weekly", "monthly"):
            for day, offset in ((date.min, -1), (date.max, 1)):
                with self.assertRaisesRegex(ValueError, "report_period_invalid"):
                    shift_report_period(day, report_type, offset)

    def test_rest_days_count_recorded_break_dates_and_exclude_leave_and_missing_dates(self):
        day = date(2026, 5, 4)
        periods = (WorkLog(1, day, "09:00", "12:00"),
                   WorkLog(1, day, "12:00", "13:00", entry_type=EntryType.BREAK),
                   WorkLog(1, day, "15:00", "15:30", entry_type=EntryType.BREAK))
        rows = (WorkLog(1, day, entries=periods),
                WorkLog(1, date(2026, 5, 5), "12:00", "13:00", entry_type=EntryType.BREAK),
                WorkLog(1, date(2026, 5, 6), entry_type=EntryType.PAID_LEAVE),
                WorkLog(1, date(2026, 5, 7), "09:00", "18:00", break_hours=1),
                WorkLog(1, date(2026, 4, 3), "12:00", "13:00", entry_type=EntryType.BREAK),
                WorkLog(1, date(2025, 7, 3), "12:00", "13:00", entry_type=EntryType.BREAK))
        for scope in ("monthly", "quarterly", "annual"):
            data = dashboard_data(rows, year=2026, month=5, scope=scope, standard_hours=8, monthly_target=168)
            self.assertEqual(data.stats.rest_days, 2 if scope == "monthly" else 3)
        self.assertEqual(dashboard_data(rows, year=2026, month=5, scope="monthly",
                                       standard_hours=8, monthly_target=168).previous_stats.rest_days, 1)
        self.assertEqual(dashboard_data((), year=2026, month=5, scope="monthly",
                                       standard_hours=8, monthly_target=168).stats.rest_days, 0)

    def test_dashboard_uses_real_days_targets_modes_and_comparison(self) -> None:
        records = (
            _record(date(2026, 3, 6), "09:00", "17:00", 1.0, EntryType.NORMAL),
            _record(date(2026, 4, 6), "09:00", "19:00", 1.0, EntryType.NORMAL),
            _record(date(2026, 4, 7), "09:00", "18:00", 1.0, EntryType.REMOTE),
            _record(date(2026, 4, 8), None, None, 0.0, EntryType.PAID_LEAVE),
        )
        data = dashboard_data(records, year=2026, month=4, scope="monthly", standard_hours=7.5, monthly_target=120)
        self.assertEqual(data.total_days, 30)
        self.assertEqual(data.previous_total_days, 31)
        self.assertEqual(data.stats.work_days, 2)
        self.assertEqual(data.stats.total_hours, 17)
        self.assertEqual(data.stats.overtime_hours, 2)
        self.assertEqual(data.previous_stats.total_hours, 7)
        self.assertEqual(data.target_hours, 120)
        self.assertEqual(dict(data.entry_types), {"normal": 9, "remote": 8, "paid_leave": 7.5})
        self.assertEqual(dict(data.work_modes), {None: 17})
        self.assertNotEqual(data.trend.bar_data, data.average.bar_data)
        self.assertEqual(data.daily_average_trend.bar_data[-1], ("04", 8.5))

    def test_dashboard_keeps_classified_duration_and_arrangement_hours_independent(self):
        day = date(2026, 4, 6)
        leave = CustomEntryType("custom:" + "a" * 32, "Study leave", "leave")
        records = aggregate_days((
            WorkLog(1, day, "09:00", "11:00", entry_type=EntryType.MEETING, work_mode=WorkMode.REMOTE),
            WorkLog(1, day, "11:00", "12:00"),
            WorkLog(1, day, "12:00", "12:30", entry_type=EntryType.BREAK),
            WorkLog(1, day, "13:00", "14:00", entry_type=leave),
            WorkLog(1, date(2026, 4, 7), entry_type=leave),
        ))
        data = dashboard_data(records, year=2026, month=4, scope="monthly", standard_hours=7.5, monthly_target=120)
        self.assertEqual(data.stats.total_hours, 3)
        self.assertEqual(dict(data.entry_types), {EntryType.MEETING: 2, EntryType.NORMAL: 1, EntryType.BREAK: 0.5, leave: 8.5})
        self.assertEqual(dict(data.work_modes), {"remote": 2, None: 1})
        self.assertEqual(sum(dict(data.work_modes).values()), data.stats.total_hours)

    def test_daily_aggregation_keeps_timed_entries_distinct_from_standalone_notes(self):
        day = date(2026, 4, 6)
        records = aggregate_days((WorkLog(1, day, note="Daily note"),
                                  WorkLog(1, day, "09:00", "17:00")))
        self.assertTrue(records[0].has_times)
        self.assertFalse(records[0].is_note_only)
        self.assertEqual(records[0].worked_hours(), 8)
        self.assertEqual((records[0].start_time, records[0].end_time), ("09:00", "17:00"))
        self.assertIn("Daily note", records[0].note)

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
        for year, month in ((0, 1), (2026, 0), (2026, 13), (None, 1)):
            with self.assertRaisesRegex(ValueError, "analytics_scope_invalid"):
                analytics_period(year, month, "monthly")

    def test_report_periods_match_calendar_week_and_month_boundaries(self) -> None:
        for day, offset, expected in (
            (date(2026, 1, 31), -1, date(2025, 12, 1)),
            (date(2026, 12, 15), 1, date(2027, 1, 1)),
            (date(2024, 2, 29), 0, date(2024, 2, 1)),
            (date(2026, 4, 15), -15, date(2025, 1, 1)),
        ):
            self.assertEqual(add_months(day, offset), expected)
        weekly = weekly_period(date(2026, 4, 22), week_start_monday=True)
        self.assertEqual(weekly.start, date(2026, 4, 20))
        self.assertEqual(weekly.end, date(2026, 4, 26))
        self.assertEqual(weekly_period(date(2026, 4, 22)).start, date(2026, 4, 19))
        for kind, start, end in (("daily", date(2026, 4, 1), date(2026, 4, 2)),
                                 ("weekly", date(2026, 4, 20), date(2026, 4, 25)),
                                 ("monthly", date(2026, 4, 2), date(2026, 4, 30))):
            with self.assertRaises(ValueError):
                validate_report_period(kind, start, end)

        monthly = monthly_period(2026, 2)
        self.assertEqual(monthly.start, date(2026, 2, 1))
        self.assertEqual(monthly.end, date(2026, 2, 28))

        with self.assertRaises(ValueError):
            validate_report_period("weekly", date(2026, 4, 2), date(2026, 4, 1))

    def test_daily_average_quarters_use_work_days_across_the_selected_year(self) -> None:
        records = (
            _record(date(2026, 1, 5), "09:00", "17:00", 0, EntryType.NORMAL),
            _record(date(2026, 1, 6), "09:00", "17:00", 0, EntryType.REMOTE),
            _record(date(2026, 2, 5), "06:00", "20:00", 0, EntryType.NORMAL),
            _record(date(2026, 3, 5), None, None, 0, EntryType.PAID_LEAVE),
            _record(date(2026, 3, 6), None, None, 0, EntryType.NORMAL),
            _record(date(2026, 7, 5), "09:00", "15:00", 0, EntryType.NORMAL),
            _record(date(2026, 12, 5), "09:00", "19:00", 0, EntryType.NORMAL),
            _record(date(2025, 1, 5), "06:00", "21:00", 0, EntryType.NORMAL),
            _record(date(2027, 1, 5), "06:00", "21:00", 0, EntryType.NORMAL),
        )
        for month in (1, 5, 12):
            data = dashboard_data(records, year=2026, month=month, scope="quarterly", standard_hours=8, monthly_target=168)
            expected = (("Q1", 10), ("Q2", 0), ("Q3", 6), ("Q4", 10))
            self.assertEqual(data.daily_average_trend.bar_data, expected)
            self.assertEqual(data.daily_average_trend.line_data, expected)
            self.assertFalse(data.daily_average_trend.leave_indices)

    def test_daily_average_annual_scope_includes_all_twelve_months(self) -> None:
        records = (
            _record(date(2026, 1, 5), "09:00", "17:00", 0, EntryType.NORMAL),
            _record(date(2026, 1, 6), "08:00", "20:00", 0, EntryType.NORMAL),
            _record(date(2026, 6, 5), "09:00", "15:00", 0, EntryType.NORMAL),
            _record(date(2026, 12, 5), "09:00", "16:00", 0, EntryType.NORMAL),
            _record(date(2026, 12, 6), None, None, 0, EntryType.PAID_LEAVE),
            _record(date(2025, 1, 5), "06:00", "21:00", 0, EntryType.NORMAL),
        )
        data = dashboard_data(records, year=2026, month=5, scope="annual", standard_hours=8, monthly_target=168)
        expected = tuple((f"{month:02d}", {1: 10, 6: 6, 12: 7}.get(month, 0)) for month in range(1, 13))
        self.assertEqual(data.daily_average_trend.bar_data, expected)
        self.assertEqual(data.daily_average_trend.line_data, expected)

    def test_daily_average_monthly_scope_keeps_six_months_across_year_boundary(self) -> None:
        records = tuple(
            _record(day, "09:00", end, 0, EntryType.NORMAL)
            for day, end in ((date(2025, 8, 5), "20:00"), (date(2025, 12, 5), "14:00"),
                             (date(2026, 1, 5), "16:00"), (date(2026, 2, 5), "19:00"),
                             (date(2026, 3, 5), "20:00"))
        )
        data = dashboard_data(records, year=2026, month=2, scope="monthly", standard_hours=8, monthly_target=168)
        self.assertEqual(data.daily_average_trend.line_data,
                         (("09", 0), ("10", 0), ("11", 0), ("12", 5), ("01", 7), ("02", 10)))

    def test_month_stats_excludes_leave_from_work_and_overtime(self) -> None:
        records = (
            _record(date(2026, 4, 6), "09:00", "19:00", 1.0, EntryType.COMP_LEAVE),
            _record(date(2026, 4, 7), "09:00", "18:00", 1.0, EntryType.NORMAL),
        )
        stats = month_stats(records, 8.0)
        self.assertEqual(stats.total_hours, 8.0)
        self.assertEqual(stats.overtime_hours, 0.0)
        self.assertEqual(stats.work_days, 1)
        self.assertEqual(stats.leave_days, 1)
        self.assertEqual(stats.average_hours, 8.0)

    def test_chart_bundle_preserves_leave_overlay_average_semantics(self) -> None:
        records = {
            date(2026, 4, 6): _record(date(2026, 4, 6), None, None, 0.0, EntryType.PAID_LEAVE),
            date(2026, 4, 7): _record(date(2026, 4, 7), "09:00", "13:00", 0.0, EntryType.COMP_LEAVE),
            date(2026, 4, 8): _record(date(2026, 4, 8), "09:00", "18:00", 1.0, EntryType.NORMAL),
        }
        bundle = monthly_chart_data(
            date(2026, 4, 1),
            date(2026, 4, 30),
            "average",
            True,
            records.get,
            standard_leave_hours=8.0,
        )
        self.assertEqual(bundle.bar_data[1], ("W2\n4/5-11", 8.0))
        self.assertEqual(bundle.leave_indices, frozenset({1}))
        self.assertEqual(bundle.leave_line_data[1], 6.0)
        self.assertEqual(bundle.leave_hours_data[1], ("W2\n4/5-11", 6.0))

    def test_quarterly_and_annual_data_are_pure_domain_preparation(self) -> None:
        by_month = {
            1: (
                _record(date(2026, 1, 5), None, None, 0.0, EntryType.PAID_LEAVE),
                _record(date(2026, 1, 6), "09:00", "13:00", 0.0, EntryType.COMP_LEAVE),
            ),
            4: (
                _record(date(2026, 4, 6), None, None, 0.0, EntryType.PAID_LEAVE),
                _record(date(2026, 4, 13), "09:00", "13:00", 0.0, EntryType.COMP_LEAVE),
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

    def test_average_chart_values_use_distinct_work_dates_in_every_scope(self):
        entries = (WorkLog(1, date(2026, 1, 5), "09:00", "13:00"),
                   WorkLog(1, date(2026, 1, 5), "14:00", "18:00"),
                   WorkLog(1, date(2026, 1, 6), "09:00", "11:00"))
        by_day = {row.day: row for row in aggregate_days(entries)}
        monthly = monthly_chart_data(date(2026, 1, 1), date(2026, 1, 31), "average", False, by_day.get)
        reader = lambda month: entries if month == 1 else ()
        quarterly = quarterly_chart_data(reader, 2026, "average", False)
        annual = annual_chart_data(reader, 2026, tuple(str(month) for month in range(1, 13)), "average", False)
        self.assertEqual([value for _label, value in monthly.bar_data if value], [5])
        self.assertEqual(quarterly.bar_data[0][1], 5)
        self.assertEqual(annual.bar_data[0][1], 5)


if __name__ == "__main__":
    unittest.main()
