"""Analytics query use cases."""

from __future__ import annotations

from calendar import monthrange
from datetime import date
import math

from worklogger.app.queries.analytics_queries import GetAnalyticsBundleQuery, GetAnalyticsDashboardQuery
from worklogger.domain.analytics.models import AnalyticsDashboard, ChartDataBundle
from worklogger.domain.analytics.rules import (
    annual_chart_data,
    monthly_chart_data,
    quarterly_chart_data,
    dashboard_data,
    analytics_period,
)
from worklogger.config.constants import MONTHLY_TARGET_HOURS_SETTING_KEY, STANDARD_WORK_HOURS_SETTING_KEY, WEEK_START_MONDAY_SETTING_KEY
from worklogger.domain.settings.repositories import SettingsRepository
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkLog
from worklogger.domain.worklog.repositories import WorkLogRepository


class GetAnalyticsBundleHandler:
    def __init__(self, repository: WorkLogRepository) -> None:
        self._repository = repository

    def handle(self, query: GetAnalyticsBundleQuery) -> Result[ChartDataBundle]:
        try:
            scope = query.scope.strip().lower()
            if scope not in {"monthly", "quarterly", "annual"}:
                raise ValueError("analytics_scope_invalid")
            if query.metric not in {"hours", "average"}:
                raise ValueError("analytics_metric_invalid")
            if scope == "monthly":
                if query.month is None:
                    raise ValueError("month_required")
                bundle = self._monthly(query)
            elif scope == "quarterly":
                bundle = self._quarterly(query)
            else:
                bundle = self._annual(query)
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        except Exception:
            return Result.failure(InfrastructureError("analytics_load_failed", "analytics_load_failed"))
        return Result.success(bundle)

    def _monthly(self, query: GetAnalyticsBundleQuery) -> ChartDataBundle:
        month = int(query.month or 0)
        _, days = monthrange(query.year, month)
        records = {
            record.day: record
            for record in self._repository.list_for_month(query.user_id, query.year, month)
        }
        return monthly_chart_data(
            date(query.year, month, 1),
            date(query.year, month, days),
            query.metric,
            query.include_leaves,
            records.get,
            standard_leave_hours=query.standard_leave_hours,
            week_start_monday=query.week_start_monday,
        )

    def _quarterly(self, query: GetAnalyticsBundleQuery) -> ChartDataBundle:
        months = self._year_records(query.user_id, query.year)
        return quarterly_chart_data(
            lambda month: months[month],
            query.year,
            query.metric,
            query.include_leaves,
            standard_leave_hours=query.standard_leave_hours,
            week_start_monday=query.week_start_monday,
        )

    def _annual(self, query: GetAnalyticsBundleQuery) -> ChartDataBundle:
        months = self._year_records(query.user_id, query.year)
        return annual_chart_data(
            lambda month: months[month],
            query.year,
            tuple(f"{month:02d}" for month in range(1, 13)),
            query.metric,
            query.include_leaves,
            standard_leave_hours=query.standard_leave_hours,
        )

    def _year_records(self, user_id: int, year: int) -> dict[int, list[WorkLog]]:
        months = {month: [] for month in range(1, 13)}
        for record in self._repository.list_range(user_id, date(year, 1, 1), date(year, 12, 31)):
            months[record.day.month].append(record)
        return months


class GetAnalyticsDashboardHandler:
    def __init__(self, repository: WorkLogRepository, settings: SettingsRepository | None = None) -> None:
        self._repository = repository
        self._settings = settings

    def handle(self, query: GetAnalyticsDashboardQuery) -> Result[AnalyticsDashboard]:
        try:
            start, end = analytics_period(query.year, query.month, query.scope)
            previous_index = start.year * 12 + start.month - 1 - (end.month - start.month + 1)
            previous_start = date(previous_index // 12, previous_index % 12 + 1, 1)
            trend_index = end.year * 12 + end.month - 1 - 5
            trend_start = date(trend_index // 12, trend_index % 12 + 1, 1)
            range_start = min(previous_start, trend_start if query.scope == "monthly" else date(query.year, 1, 1))
            range_end = end if query.scope == "monthly" else date(query.year, 12, 31)
            standard = self._number(query.user_id, STANDARD_WORK_HOURS_SETTING_KEY, 8.0, 1.0, 24.0)
            target = self._number(query.user_id, MONTHLY_TARGET_HOURS_SETTING_KEY, 168.0, 0.0, 400.0)
            value = dashboard_data(
                self._repository.list_range(query.user_id, range_start, range_end), year=query.year, month=query.month,
                scope=query.scope, standard_hours=standard, monthly_target=target,
                week_start_monday=self._settings is not None and self._settings.get(query.user_id, WEEK_START_MONDAY_SETTING_KEY, "0") == "1",
            )
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        except Exception:
            return Result.failure(InfrastructureError("analytics_load_failed", "analytics_load_failed"))
        return Result.success(value)

    def _number(self, user_id: int, key: str, default: float, minimum: float, maximum: float) -> float:
        value = self._settings.get(user_id, key, str(default)) if self._settings is not None else default
        try:
            number = float(value)
            if not math.isfinite(number):
                raise ValueError("setting_number_invalid")
            return max(minimum, min(maximum, number))
        except (TypeError, ValueError):
            return default
