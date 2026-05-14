"""Work log command and query use cases."""

from __future__ import annotations

from worklogger.app.commands.work_log_commands import DeleteWorkLogCommand, SaveWorkLogCommand
from worklogger.app.event_bus import EventBus, WorkLogSaved
from worklogger.app.queries.work_log_queries import (
    GetAllWorkLogsQuery,
    GetMonthRecordsQuery,
    GetWorkLogQuery,
)
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkLog
from worklogger.domain.worklog.repositories import WorkLogRepository
from worklogger.domain.worklog.rules import normalize_work_log, normalize_work_type


class SaveWorkLogHandler:
    def __init__(
        self,
        repository: WorkLogRepository,
        event_bus: EventBus | None = None,
    ) -> None:
        self._repository = repository
        self._event_bus = event_bus

    def handle(self, command: SaveWorkLogCommand) -> Result[WorkLog]:
        try:
            work_log = normalize_work_log(
                WorkLog(
                    user_id=command.user_id,
                    day=command.day,
                    start_time=command.start_time,
                    end_time=command.end_time,
                    break_hours=command.break_hours,
                    note=command.note,
                    work_type=normalize_work_type(command.work_type),
                )
            )
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        self._repository.save(work_log)
        if self._event_bus is not None:
            self._event_bus.publish(WorkLogSaved(user_id=work_log.user_id, day=work_log.day))
        return Result.success(work_log)


class DeleteWorkLogHandler:
    def __init__(self, repository: WorkLogRepository) -> None:
        self._repository = repository

    def handle(self, command: DeleteWorkLogCommand) -> Result[None]:
        self._repository.remove(command.user_id, command.day)
        return Result.success(None)


class GetWorkLogHandler:
    def __init__(self, repository: WorkLogRepository) -> None:
        self._repository = repository

    def handle(self, query: GetWorkLogQuery) -> Result[WorkLog | None]:
        return Result.success(self._repository.get_for_day(query.user_id, query.day))


class GetMonthRecordsHandler:
    def __init__(self, repository: WorkLogRepository) -> None:
        self._repository = repository

    def handle(self, query: GetMonthRecordsQuery) -> Result[tuple[WorkLog, ...]]:
        return Result.success(
            self._repository.list_for_month(query.user_id, query.year, query.month)
        )


class GetAllWorkLogsHandler:
    def __init__(self, repository: WorkLogRepository) -> None:
        self._repository = repository

    def handle(self, query: GetAllWorkLogsQuery) -> Result[tuple[WorkLog, ...]]:
        return Result.success(self._repository.list_all(query.user_id))
