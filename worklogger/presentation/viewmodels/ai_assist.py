"""AI Assist presentation ViewModel."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from worklogger.app.commands.ai_commands import SendAiChatMessageCommand
from worklogger.app.queries.ai_queries import BuildAiContextQuery
from worklogger.app.use_cases.ai import AiChatResult, AiContextResult
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result


class AiChatHandlerProtocol(Protocol):
    def handle(self, command: SendAiChatMessageCommand) -> Result[AiChatResult]:
        ...


class AiContextHandlerProtocol(Protocol):
    def handle(self, query: BuildAiContextQuery) -> Result[AiContextResult]:
        ...


@dataclass(frozen=True)
class AiChatState:
    user_id: int
    history: tuple[dict[str, str], ...] = ()


class AiAssistViewModel:
    def __init__(
        self,
        *,
        user_id: int,
        chat_handler: AiChatHandlerProtocol,
        context_handler: AiContextHandlerProtocol | None = None,
        language: str = "en_US",
    ) -> None:
        self._user_id = user_id
        self._chat_handler = chat_handler
        self._context_handler = context_handler
        self._language = language

    def initial_state(self) -> AiChatState:
        return AiChatState(user_id=self._user_id)

    def send(
        self,
        state: AiChatState,
        message: str,
        *,
        context: str = "",
        selected_day: date | None = None,
        period_type: str = "daily",
    ) -> Result[AiChatState]:
        if self._context_handler is not None and selected_day is not None:
            built = self._context_handler.handle(
                BuildAiContextQuery(
                    user_id=self._user_id,
                    selected_day=selected_day,
                    period_type=period_type,
                )
            )
            if not built.ok or built.value is None:
                return Result.failure(
                    built.error or ValidationError("ai_context_failed", "ai_context_failed")
                )
            context = built.value.content
        result = self._chat_handler.handle(
            SendAiChatMessageCommand(
                user_id=self._user_id,
                message=message,
                history=state.history,
                context=context,
                language=self._language,
            )
        )
        if not result.ok or result.value is None:
            return Result.failure(result.error or ValidationError("ai_chat_failed", "ai_chat_failed"))
        return Result.success(AiChatState(user_id=self._user_id, history=result.value.history))
