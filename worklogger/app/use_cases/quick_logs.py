"""Quick log command and query use cases."""

from __future__ import annotations

from datetime import datetime, timezone

from worklogger.app.commands.quick_log_commands import (
    AddQuickLogCommand,
    DeleteQuickLogCommand,
    UpdateQuickLogCommand,
)
from worklogger.app.queries.quick_log_queries import (
    GetQuickLogsForDayQuery,
    GetQuickLogsForRangeQuery,
)
from worklogger.domain.quicklog.models import QuickLog
from worklogger.domain.quicklog.repositories import QuickLogRepository
from worklogger.domain.quicklog.rules import normalize_quick_log
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result


class AddQuickLogHandler:
    def __init__(self, repository: QuickLogRepository) -> None:
        self._repository = repository

    def handle(self, command: AddQuickLogCommand) -> Result[QuickLog]:
        try:
            quick_log = normalize_quick_log(
                QuickLog(
                    id=None,
                    user_id=command.user_id,
                    day=command.day,
                    description=command.description,
                    start_time=command.start_time,
                    end_time=command.end_time,
                    created_at=datetime.now(timezone.utc),
                )
            )
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        return Result.success(self._repository.add(quick_log))


class UpdateQuickLogHandler:
    def __init__(self, repository: QuickLogRepository) -> None:
        self._repository = repository

    def handle(self, command: UpdateQuickLogCommand) -> Result[QuickLog]:
        try:
            quick_log = normalize_quick_log(
                QuickLog(
                    id=command.quick_log_id,
                    user_id=command.user_id,
                    day=command.day,
                    description=command.description,
                    start_time=command.start_time,
                    end_time=command.end_time,
                )
            )
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        self._repository.update(quick_log)
        return Result.success(quick_log)


class DeleteQuickLogHandler:
    def __init__(self, repository: QuickLogRepository) -> None:
        self._repository = repository

    def handle(self, command: DeleteQuickLogCommand) -> Result[None]:
        self._repository.remove(command.user_id, command.quick_log_id)
        return Result.success(None)


class GetQuickLogsForDayHandler:
    def __init__(self, repository: QuickLogRepository) -> None:
        self._repository = repository

    def handle(self, query: GetQuickLogsForDayQuery) -> Result[tuple[QuickLog, ...]]:
        return Result.success(self._repository.list_for_day(query.user_id, query.day))


class GetQuickLogsForRangeHandler:
    def __init__(self, repository: QuickLogRepository) -> None:
        self._repository = repository

    def handle(self, query: GetQuickLogsForRangeQuery) -> Result[tuple[QuickLog, ...]]:
        if query.end_day < query.start_day:
            return Result.failure(ValidationError("date_range_invalid", "date_range_invalid"))
        return Result.success(
            self._repository.list_for_range(
                query.user_id,
                query.start_day,
                query.end_day,
            )
        )
