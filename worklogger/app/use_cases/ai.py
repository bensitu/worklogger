"""AI-assisted text use cases."""

from __future__ import annotations

from worklogger.app.failures import infrastructure_failure

from dataclasses import dataclass

from worklogger.app.commands.ai_commands import RewriteTextCommand, SendAiChatMessageCommand
from worklogger.app.job_runner import CancellationToken
from worklogger.app.ports import AIGateway, AIRequest
from worklogger.app.use_cases.ai_context import AiContextResult as AiContextResult
from worklogger.app.use_cases.ai_context import BuildAiContextHandler as BuildAiContextHandler
from worklogger.app.use_cases.user_profile import profile_display_name
from worklogger.app.use_cases.text_prompts import output_language_instruction, profile_instruction, rewrite_messages
from worklogger.domain.auth.repositories import UserProfileRepository
from worklogger.domain.shared.errors import CancellationError, InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result


@dataclass(frozen=True)
class RewriteTextResult:
    content: str


@dataclass(frozen=True)
class AiChatResult:
    reply: str
    history: tuple[dict[str, str], ...]


class RewriteTextHandler:
    @property
    def available(self) -> bool:
        return self._gateway is not None and bool(getattr(self._gateway, "available", True))

    def __init__(
        self,
        gateway: AIGateway | None = None,
        *,
        model: str = "default",
        timeout_seconds: float = 30.0,
        profiles: UserProfileRepository | None = None,
    ) -> None:
        self._gateway = gateway
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._profiles = profiles

    def handle(
        self,
        command: RewriteTextCommand,
        cancellation_token: CancellationToken | None = None,
    ) -> Result[RewriteTextResult]:
        if _cancelled(cancellation_token):
            return Result.failure(_cancelled_error())
        content = str(command.content or "").strip()
        if not content:
            return Result.failure(ValidationError("rewrite_content_required", "rewrite_content_required"))
        if self._gateway is None:
            return Result.failure(
                InfrastructureError(
                    "ai_rewrite_not_configured",
                    "ai_rewrite_not_configured",
                )
            )
        try:
            display_name = profile_display_name(self._profiles, command.user_id)
            prompt_values = dict(content=content, context=command.context, output_language=command.output_language,
                                 instructions=command.instructions, display_name=display_name)
            response = self._gateway.generate(
                AIRequest(
                    messages=rewrite_messages(**prompt_values),
                    local_messages=rewrite_messages(**prompt_values, compact=True),
                    model=self._model,
                    timeout_seconds=self._timeout_seconds,
                    cancellation_token=cancellation_token,
                )
            )
        except Exception as exc:
            return Result.failure(
                infrastructure_failure('ai_rewrite_failed', exc, logger_name=__name__)
            )
        if _cancelled(cancellation_token):
            return Result.failure(_cancelled_error())
        if not response.ok or response.value is None:
            return Result.failure(response.error or InfrastructureError("ai_rewrite_failed", "ai_rewrite_failed"))
        rewritten = response.value.text.strip()
        if not rewritten:
            return Result.failure(InfrastructureError("ai_rewrite_empty", "ai_rewrite_empty"))
        return Result.success(RewriteTextResult(rewritten))


class AiChatHandler:
    def __init__(
        self,
        gateway: AIGateway | None = None,
        *,
        model: str = "default",
        timeout_seconds: float = 60.0,
        max_history_messages: int = 12,
        profiles: UserProfileRepository | None = None,
    ) -> None:
        self._gateway = gateway
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_history_messages = max(0, int(max_history_messages))
        self._profiles = profiles

    @property
    def available(self) -> bool:
        return self._gateway is not None and bool(getattr(self._gateway, "available", True))

    def handle(
        self,
        command: SendAiChatMessageCommand,
        cancellation_token: CancellationToken | None = None,
    ) -> Result[AiChatResult]:
        if _cancelled(cancellation_token):
            return Result.failure(_cancelled_error("ai_chat_cancelled"))
        message = str(command.message or "").strip()
        if not message:
            return Result.failure(ValidationError("ai_chat_message_required", "ai_chat_message_required"))
        if self._gateway is None:
            return Result.failure(
                InfrastructureError("ai_chat_not_configured", "ai_chat_not_configured")
            )
        try:
            display_name = profile_display_name(self._profiles, command.user_id)
        except Exception as error:
            return Result.failure(infrastructure_failure('user_profile_load_failed', error, logger_name=__name__))
        history = _bounded_history(command.history, self._max_history_messages)
        request_messages = (
            {
                "role": "system",
                "content": (
                    "You are WorkLogger AI Assist. Help with work log analysis, notes, "
                    "and reports. Preserve facts and avoid inventing records."
                    + output_language_instruction(command.output_language, conversation=True)
                    + profile_instruction(display_name)
                ),
            },
            *history,
            {
                "role": "user",
                "content": _chat_user_content(
                    message=message,
                    context=command.context,
                ),
            },
        )
        try:
            response = self._gateway.generate(
                AIRequest(
                    messages=request_messages,
                    model=self._model,
                    timeout_seconds=self._timeout_seconds,
                    cancellation_token=cancellation_token,
                )
            )
        except Exception as exc:
            return Result.failure(
                infrastructure_failure('ai_chat_failed', exc, logger_name=__name__)
            )
        if _cancelled(cancellation_token):
            return Result.failure(_cancelled_error("ai_chat_cancelled"))
        if not response.ok or response.value is None:
            return Result.failure(response.error or InfrastructureError("ai_chat_failed", "ai_chat_failed"))
        reply = response.value.text.strip()
        if not reply:
            return Result.failure(InfrastructureError("ai_chat_empty", "ai_chat_empty"))
        next_history = _bounded_history(
            (
                *history,
                {"role": "user", "content": message},
                {"role": "assistant", "content": reply},
            ),
            self._max_history_messages,
        )
        return Result.success(AiChatResult(reply=reply, history=next_history))


def _bounded_history(
    history: tuple[object, ...],
    max_messages: int,
) -> tuple[dict[str, str], ...]:
    clean: list[dict[str, str]] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            clean.append({"role": role, "content": content})
    return tuple(clean[-max_messages:]) if max_messages else ()


def _chat_user_content(
    *,
    message: str,
    context: str,
) -> str:
    context_text = str(context or "").strip()
    if context_text:
        return f"Context:\n{context_text}\n\nUser:\n{message}"
    return message


def _cancelled(cancellation_token: CancellationToken | None) -> bool:
    value = getattr(cancellation_token, "is_cancelled", False)
    return bool(value() if callable(value) else value)


def _cancelled_error(code: str = "ai_rewrite_cancelled") -> CancellationError:
    return CancellationError(code, code)
