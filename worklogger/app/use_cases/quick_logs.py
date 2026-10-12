"""Read-only queries for historical quick log entries."""

from __future__ import annotations

from worklogger.app.queries.quick_log_queries import (
    GetQuickLogsForDayQuery,
    GetQuickLogsForRangeQuery,
)
from worklogger.domain.quicklog.models import QuickLog
from worklogger.domain.quicklog.repositories import QuickLogRepository
from worklogger.domain.shared.errors import ValidationError, InfrastructureError
from worklogger.domain.shared.result import Result


class GetQuickLogsForDayHandler:
    def __init__(self, repository: QuickLogRepository) -> None:
        self._repository = repository

    def handle(self, query: GetQuickLogsForDayQuery) -> Result[tuple[QuickLog, ...]]:
        try:
            return Result.success(self._repository.list_for_day(query.user_id, query.day))
        except Exception:
            return Result.failure(InfrastructureError("quick_log_load_failed", "quick_log_load_failed"))


class GetQuickLogsForRangeHandler:
    def __init__(self, repository: QuickLogRepository) -> None:
        self._repository = repository

    def handle(self, query: GetQuickLogsForRangeQuery) -> Result[tuple[QuickLog, ...]]:
        if query.end_day < query.start_day:
            return Result.failure(ValidationError("date_range_invalid", "date_range_invalid"))
        try:
            return Result.success(self._repository.list_for_range(query.user_id, query.start_day, query.end_day))
        except Exception:
            return Result.failure(InfrastructureError("quick_log_load_failed", "quick_log_load_failed"))
