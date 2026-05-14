"""Analytics query use cases."""

from __future__ import annotations

from calendar import monthrange
from datetime import date

from worklogger.app.queries.analytics_queries import GetAnalyticsBundleQuery
from worklogger.domain.analytics.models import ChartDataBundle
from worklogger.domain.analytics.rules import (
    annual_chart_data,
    monthly_chart_data,
    quarterly_chart_data,
)
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
        )

    def _quarterly(self, query: GetAnalyticsBundleQuery) -> ChartDataBundle:
        return quarterly_chart_data(
            lambda month: self._month_records(query.user_id, query.year, month),
            query.year,
            query.metric,
            query.include_leaves,
            standard_leave_hours=query.standard_leave_hours,
        )

    def _annual(self, query: GetAnalyticsBundleQuery) -> ChartDataBundle:
        return annual_chart_data(
            lambda month: self._month_records(query.user_id, query.year, month),
            query.year,
            tuple(f"{month:02d}" for month in range(1, 13)),
            query.metric,
            query.include_leaves,
            standard_leave_hours=query.standard_leave_hours,
        )

    def _month_records(self, user_id: int, year: int, month: int) -> tuple[WorkLog, ...]:
        return self._repository.list_for_month(user_id, year, month)
