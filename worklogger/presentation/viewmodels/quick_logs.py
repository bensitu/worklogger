"""Quick Log presentation ViewModel."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from worklogger.app.commands.quick_log_commands import (
    AddQuickLogCommand,
    DeleteQuickLogCommand,
    UpdateQuickLogCommand,
)
from worklogger.app.queries.quick_log_queries import GetQuickLogsForDayQuery
from worklogger.domain.quicklog.models import QuickLog
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result


class AddQuickLogHandlerProtocol(Protocol):
    def handle(self, command: AddQuickLogCommand) -> Result[QuickLog]:
        ...


class UpdateQuickLogHandlerProtocol(Protocol):
    def handle(self, command: UpdateQuickLogCommand) -> Result[QuickLog]:
        ...


class DeleteQuickLogHandlerProtocol(Protocol):
    def handle(self, command: DeleteQuickLogCommand) -> Result[None]:
        ...


class GetQuickLogsForDayHandlerProtocol(Protocol):
    def handle(self, query: GetQuickLogsForDayQuery) -> Result[tuple[QuickLog, ...]]:
        ...


@dataclass(frozen=True)
class QuickLogEditorState:
    user_id: int
    day: date
    quick_logs: tuple[QuickLog, ...] = ()


class QuickLogEditorViewModel:
    def __init__(
        self,
        *,
        user_id: int,
        add_handler: AddQuickLogHandlerProtocol,
        update_handler: UpdateQuickLogHandlerProtocol,
        delete_handler: DeleteQuickLogHandlerProtocol,
        get_day_handler: GetQuickLogsForDayHandlerProtocol,
    ) -> None:
        self._user_id = user_id
        self._add_handler = add_handler
        self._update_handler = update_handler
        self._delete_handler = delete_handler
        self._get_day_handler = get_day_handler

    def load(self, day: date) -> Result[QuickLogEditorState]:
        result = self._get_day_handler.handle(GetQuickLogsForDayQuery(self._user_id, day))
        if not result.ok or result.value is None:
            return Result.failure(result.error or _validation("quick_log_load_failed"))
        return Result.success(
            QuickLogEditorState(
                user_id=self._user_id,
                day=day,
                quick_logs=result.value,
            )
        )

    def add(
        self,
        day: date,
        *,
        description: str,
        start_time: str = "",
        end_time: str = "",
    ) -> Result[QuickLogEditorState]:
        result = self._add_handler.handle(
            AddQuickLogCommand(
                user_id=self._user_id,
                day=day,
                description=description,
                start_time=start_time,
                end_time=end_time,
            )
        )
        if not result.ok:
            return Result.failure(result.error or _validation("quick_log_add_failed"))
        return self.load(day)

    def update(
        self,
        quick_log_id: int,
        day: date,
        *,
        description: str,
        start_time: str = "",
        end_time: str = "",
    ) -> Result[QuickLogEditorState]:
        result = self._update_handler.handle(
            UpdateQuickLogCommand(
                user_id=self._user_id,
                quick_log_id=quick_log_id,
                day=day,
                description=description,
                start_time=start_time,
                end_time=end_time,
            )
        )
        if not result.ok:
            return Result.failure(result.error or _validation("quick_log_update_failed"))
        return self.load(day)

    def delete(self, quick_log_id: int, day: date) -> Result[QuickLogEditorState]:
        result = self._delete_handler.handle(
            DeleteQuickLogCommand(
                user_id=self._user_id,
                quick_log_id=quick_log_id,
            )
        )
        if not result.ok:
            return Result.failure(result.error or _validation("quick_log_delete_failed"))
        return self.load(day)


def _validation(code: str) -> ValidationError:
    return ValidationError(code, code)

