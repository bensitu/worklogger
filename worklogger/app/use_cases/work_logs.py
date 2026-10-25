"""Work log queries for calendar views and exports."""

from __future__ import annotations

from worklogger.app.failures import infrastructure_failure

from datetime import date

from worklogger.app.queries.work_log_queries import (
    GetAllWorkLogsQuery,
    GetMonthRecordsQuery,
)
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkLog
from worklogger.domain.worklog.repositories import WorkLogRepository


def _read_work_log_range(repository: WorkLogRepository, user_id: int, start: date, end: date) -> Result[tuple[WorkLog, ...]]:
    try:
        return Result.success(repository.list_range(user_id, start, end))
    except Exception as error:
        return Result.failure(infrastructure_failure("worklog_load_failed", error, logger_name=__name__))


class GetMonthRecordsHandler:
    def __init__(self, repository: WorkLogRepository) -> None:
        self._repository = repository

    def handle(self, query: GetMonthRecordsQuery) -> Result[tuple[WorkLog, ...]]:
        try:
            date(query.year, query.month, 1)
        except (TypeError, ValueError):
            return Result.failure(ValidationError("date_range_invalid", "date_range_invalid"))
        try:
            return Result.success(self._repository.list_for_month(query.user_id, query.year, query.month))
        except Exception as error:
            return Result.failure(infrastructure_failure('worklog_load_failed', error, logger_name=__name__))

    def list_range(self, user_id: int, start: date, end: date) -> Result[tuple[WorkLog, ...]]:
        return _read_work_log_range(self._repository, user_id, start, end)


class GetAllWorkLogsHandler:
    def __init__(self, repository: WorkLogRepository, *, include_note_only: bool = False) -> None:
        self._repository = repository
        self._include_note_only = include_note_only

    def handle(self, query: GetAllWorkLogsQuery) -> Result[tuple[WorkLog, ...]]:
        try:
            reader = getattr(self._repository, "list_export_rows", self._repository.list_all) if self._include_note_only else self._repository.list_all
            return Result.success(reader(query.user_id))
        except Exception as error:
            return Result.failure(infrastructure_failure('worklog_load_failed', error, logger_name=__name__))

    def list_range(self, user_id: int, start, end) -> Result[tuple[WorkLog, ...]]:
        return _read_work_log_range(self._repository, user_id, start, end)
