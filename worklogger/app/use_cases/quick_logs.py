"""Read-only queries for historical quick log entries."""

from __future__ import annotations

from worklogger.app.use_cases._errors import infrastructure_failure
from datetime import date

from worklogger.app.queries.quick_log_queries import (
    GetQuickLogsForDayQuery,
    GetQuickLogsForRangeQuery,
)
from worklogger.domain.quicklog.models import QuickLog
from worklogger.domain.quicklog.repositories import QuickLogRepository
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result


class GetQuickLogsForDayHandler:
    def __init__(self, repository: QuickLogRepository) -> None:
        self._repository = repository

    def handle(self, query: GetQuickLogsForDayQuery) -> Result[tuple[QuickLog, ...]]:
        if type(query.day) is not date:
            return Result.failure(ValidationError("date_range_invalid", "date_range_invalid"))
        try:
            return Result.success(self._repository.list_for_day(query.user_id, query.day))
        except Exception as error:
            return Result.failure(infrastructure_failure('quick_log_load_failed', error, logger_name=__name__))


class GetQuickLogsForRangeHandler:
    def __init__(self, repository: QuickLogRepository) -> None:
        self._repository = repository

    def handle(self, query: GetQuickLogsForRangeQuery) -> Result[tuple[QuickLog, ...]]:
        if type(query.start_day) is not date or type(query.end_day) is not date or query.end_day < query.start_day:
            return Result.failure(ValidationError("date_range_invalid", "date_range_invalid"))
        try:
            return Result.success(self._repository.list_for_range(query.user_id, query.start_day, query.end_day))
        except Exception as error:
            return Result.failure(infrastructure_failure('quick_log_load_failed', error, logger_name=__name__))
