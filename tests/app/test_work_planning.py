"""Work-plan calculations and account preferences across analytics periods."""

from datetime import date
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from tests.app.test_application_use_cases import MemorySettingsRepository
from worklogger.app.queries.analytics_queries import GetAnalyticsDashboardQuery
from worklogger.app.use_cases.analytics import GetAnalyticsDashboardHandler
from worklogger.app.use_cases.work_planning import WorkPlanningService
from worklogger.config.constants import (HOLIDAY_REGION_SETTING_KEY, SHOW_HOLIDAYS_SETTING_KEY,
    WORK_SCHEDULE_SETTING_KEY, WORK_TARGET_MODE_SETTING_KEY)
from worklogger.domain.calendar.models import Holiday
from worklogger.domain.settings.work_schedule import WorkSchedule
from worklogger.domain.worklog.models import WorkLog


class WorkPlanningTests(TestCase):
    def setUp(self):
        self.settings = MemorySettingsRepository()
        self.settings.set(1, WORK_TARGET_MODE_SETTING_KEY, "schedule")
        self.provider = Mock()
        self.planning = WorkPlanningService(self.settings, self.provider, country="JP")

    def test_disabled_holidays_do_not_load_a_provider_or_use_the_region(self):
        self.settings.set(1, SHOW_HOLIDAYS_SETTING_KEY, "0")
        self.settings.set(1, HOLIDAY_REGION_SETTING_KEY, "US/CA")
        self.settings.set(1, WORK_SCHEDULE_SETTING_KEY, WorkSchedule.preset("two_and_a_half_days_off").encode())
        result = self.planning.summarize(1, date(2026, 10, 1), date(2026, 10, 31), standard_hours=8, monthly_target=168)
        self.assertEqual((result.planned_days, result.target_hours, result.error_code), (19.5, 156, ""))
        self.provider.list_for_range.assert_not_called()

    def test_enabled_holidays_use_selected_region_and_deduct_each_scheduled_date_once(self):
        self.settings.set(1, SHOW_HOLIDAYS_SETTING_KEY, "1")
        self.settings.set(1, HOLIDAY_REGION_SETTING_KEY, "US/CA")
        self.settings.set(1, WORK_SCHEDULE_SETTING_KEY, WorkSchedule.preset("two_and_a_half_days_off").encode())
        self.provider.list_for_range.return_value = tuple(Holiday(day, "Holiday") for day in (
            date(2026, 10, 1), date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3), date(2026, 9, 30)))
        result = self.planning.summarize(1, date(2026, 10, 1), date(2026, 10, 31), standard_hours=8, monthly_target=168)
        self.assertEqual((result.planned_days, result.target_hours), (18, 144))
        self.provider.list_for_range.assert_called_once_with("US", date(2026, 10, 1), date(2026, 10, 31), subdivision="CA")

    def test_automatic_goals_cover_the_selected_period_and_do_not_reclassify_work(self):
        self.settings.set(1, SHOW_HOLIDAYS_SETTING_KEY, "1")
        self.provider.list_for_range.return_value = (Holiday(date(2024, 2, 1), "Holiday"),)
        records = SimpleNamespace(list_range=lambda *_args: (WorkLog(1, date(2024, 2, 1), "09:00", "19:00"),))
        handler = GetAnalyticsDashboardHandler(records, self.settings, planning=self.planning)
        for scope, expected in (("monthly", 28), ("quarterly", 90), ("annual", 365)):
            result = handler.handle(GetAnalyticsDashboardQuery(1, 2024, 2, scope))
            self.assertTrue(result.ok, result.error)
            self.assertEqual((result.value.planned_work_days, result.value.target_hours), (expected, expected * 8))
            self.assertEqual((result.value.stats.work_days, result.value.stats.total_hours, result.value.stats.overtime_hours), (1, 10, 2))

    def test_unavailable_holidays_leave_actuals_and_custom_goals_available(self):
        self.settings.set(1, SHOW_HOLIDAYS_SETTING_KEY, "1")
        self.provider.list_for_range.side_effect = OSError("Unavailable holiday data")
        result = self.planning.summarize(1, date(2024, 1, 1), date(2024, 3, 31), standard_hours=8, monthly_target=168)
        self.assertIsNone(result.target_hours)
        self.assertIsNone(result.planned_days)
        self.assertEqual(result.error_code, "work_plan_holidays_failed")
        self.settings.delete(1, WORK_TARGET_MODE_SETTING_KEY)
        manual = self.planning.summarize(1, date(2024, 1, 1), date(2024, 3, 31), standard_hours=8, monthly_target=168)
        self.assertEqual((manual.target_mode, manual.target_hours), ("manual", 504))
        missing = WorkPlanningService(self.settings, self.provider)
        self.assertEqual(missing.summarize(1, date(2024, 1, 1), date(2024, 1, 31),
            standard_hours=8, monthly_target=168).error_code, "work_plan_region_required")
