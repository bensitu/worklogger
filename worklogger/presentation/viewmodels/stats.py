"""Stats panel presentation ViewModel."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from calendar import monthrange
from typing import Protocol

from worklogger.app.queries.work_log_queries import GetMonthRecordsQuery
from worklogger.domain.analytics.rules import month_stats
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkLog
from worklogger.app.use_cases.work_planning import WorkPlanningService
from worklogger.domain.shared.errors import InfrastructureError


class StatsMonthRecordsHandler(Protocol):
    def handle(self, query: GetMonthRecordsQuery) -> Result[tuple[WorkLog, ...]]:
        ...


@dataclass(frozen=True)
class StatsPanelState:
    total_hours: float
    overtime_hours: float
    work_days: int
    leave_days: int
    average_hours: float
    monthly_target_hours: float | None
    target_progress: float
    target_error: str = ""


class StatsPanelViewModel:
    def __init__(
        self,
        *,
        user_id: int,
        month_records_handler: StatsMonthRecordsHandler,
        planning: WorkPlanningService | None = None,
    ) -> None:
        self._user_id = user_id
        self._month_records_handler = month_records_handler
        self._planning = planning

    def build_month(
        self,
        *,
        year: int,
        month: int,
        standard_work_hours: float = 8.0,
        monthly_target_hours: float = 0.0,
    ) -> Result[StatsPanelState]:
        try:
            year = int(year)
            month = int(month)
            if month < 1 or month > 12:
                raise ValueError("month_invalid")
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))

        records = self._month_records_handler.handle(
            GetMonthRecordsQuery(
                user_id=self._user_id,
                year=year,
                month=month,
            )
        )
        if not records.ok:
            return Result.failure(records.error or ValidationError("stats_load_failed", "stats_load_failed"))

        stats = month_stats(records.value or (), float(standard_work_hours))
        target = max(float(monthly_target_hours or 0), 0.0)
        target_error = ""
        if self._planning is not None:
            try:
                plan = self._planning.summarize(self._user_id, date(year, month, 1),
                    date(year, month, monthrange(year, month)[1]), standard_hours=standard_work_hours, monthly_target=target)
                target, target_error = plan.target_hours, plan.error_code
            except Exception:
                return Result.failure(InfrastructureError("stats_load_failed", "stats_load_failed"))
        progress = stats.total_hours / target if target else 0.0
        return Result.success(
            StatsPanelState(
                total_hours=stats.total_hours,
                overtime_hours=stats.overtime_hours,
                work_days=stats.work_days,
                leave_days=stats.leave_days,
                average_hours=stats.average_hours,
                monthly_target_hours=target,
                target_progress=max(0.0, min(progress, 1.0)),
                target_error=target_error,
            )
        )
