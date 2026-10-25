"""Account work plans and targets using the selected public-holiday preferences."""

from dataclasses import dataclass
from datetime import date

from worklogger.config.constants import (HOLIDAY_REGION_SETTING_KEY, SHOW_HOLIDAYS_SETTING_KEY,
    WORK_SCHEDULE_SETTING_KEY, WORK_TARGET_MODE_SETTING_KEY)
from worklogger.domain.calendar.repositories import HolidayProvider
from worklogger.domain.settings.repositories import SettingsRepository
from worklogger.domain.settings.values import setting_bool
from worklogger.domain.settings.work_schedule import WorkSchedule
from worklogger.app.use_cases._errors import infrastructure_failure


@dataclass(frozen=True)
class WorkPlanSummary:
    planned_days: float | None
    target_hours: float | None
    target_mode: str
    error_code: str = ""


class WorkPlanningService:
    def __init__(self, settings: SettingsRepository | None, holidays: HolidayProvider | None = None,
                 *, country: str = ""):
        self._settings, self._holidays, self._country = settings, holidays, country

    def summarize(self, user_id: int, start: date, end: date, *, standard_hours: float,
                  monthly_target: float) -> WorkPlanSummary:
        mode = "schedule" if self._get(user_id, WORK_TARGET_MODE_SETTING_KEY, "manual") == "schedule" else "manual"
        schedule = WorkSchedule.from_setting(self._get(user_id, WORK_SCHEDULE_SETTING_KEY))
        months = (end.year - start.year) * 12 + end.month - start.month + 1
        manual_target = monthly_target * months
        holidays = ()
        if setting_bool(self._get(user_id, SHOW_HOLIDAYS_SETTING_KEY, "1"), True):
            region = str(self._get(user_id, HOLIDAY_REGION_SETTING_KEY, "") or "")
            country, _separator, subdivision = region.partition("/")
            country = country or self._country
            error = "work_plan_region_required" if not country else "work_plan_holidays_failed"
            try:
                if not country or self._holidays is None:
                    raise ValueError("holiday_provider_unavailable")
                entries = self._holidays.list_for_range(country, start, end, subdivision=subdivision or None)
                holidays = tuple(entry.day for entry in entries)
            except Exception as error_detail:
                infrastructure_failure("work_plan_holidays_failed", error_detail, logger_name=__name__)
                return WorkPlanSummary(None, manual_target if mode == "manual" else None, mode, error)
        planned = schedule.planned_days(start, end, holidays=holidays)
        return WorkPlanSummary(planned, planned * standard_hours if mode == "schedule" else manual_target, mode)

    def _get(self, user_id, key, default=None):
        return self._settings.get(user_id, key, default) if self._settings is not None else default
