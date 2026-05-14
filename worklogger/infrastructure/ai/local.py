"""Local-model AI gateway helpers."""

from __future__ import annotations

from collections.abc import Callable
import re

from worklogger.app.ports import AIRequest, AIResponse
from worklogger.domain.shared.errors import InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result

_THINKING_RE = re.compile(
    r"(<\|begin_of_thought\|>.*?<\|end_of_thought\|>|<think>.*?</think>|"
    r"<thinking>.*?</thinking>)",
    re.DOTALL | re.IGNORECASE,
)
_THINKING_MARKER_RE = re.compile(
    r"(?:</?\s*(?:think|thinking)\s*>|<\|begin_of_thought\|>|<\|end_of_thought\|>)",
    re.IGNORECASE,
)
_FINAL_PREFIX_RE = re.compile(r"^\s*(?:final answer|final output|answer)\s*:\s*", re.IGNORECASE)
_NO_THINK_DIRECTIVE = "/no_think"
_NO_THINK_RULE = (
    "Do not output hidden reasoning, analysis, thinking process, or <think> blocks. "
    "Return only the final answer."
)

LocalGenerator = Callable[[tuple[dict[str, str], ...], int], str]


class LocalModelGateway:
    def __init__(
        self,
        *,
        generator: LocalGenerator | None,
        model_id: str,
        catalog_entry: dict[str, object] | None = None,
        provider: str = "local",
        max_output_tokens: int = 2048,
    ) -> None:
        self._generator = generator
        self._model_id = str(model_id or "").strip()
        self._catalog_entry = catalog_entry or {}
        self._provider = provider
        self._max_output_tokens = max(1, int(max_output_tokens))

    def generate(self, request: AIRequest) -> Result[AIResponse]:
        if self._generator is None:
            return Result.failure(
                InfrastructureError(
                    "local_model_not_configured",
                    "local_model_not_configured",
                )
            )
        if not self._model_id:
            return Result.failure(ValidationError("local_model_id_required", "local_model_id_required"))
        try:
            messages = _messages_with_no_think(
                tuple(dict(message) for message in request.messages),
                self._model_id,
                self._catalog_entry,
            )
            raw = self._generator(messages, self._max_output_tokens)
            text = strip_thinking(raw)
            if not text:
                return Result.failure(InfrastructureError("local_model_empty_response", "local_model_empty_response"))
            return Result.success(AIResponse(text=text, provider=self._provider))
        except Exception as exc:
            return Result.failure(
                InfrastructureError(
                    "local_model_generation_failed",
                    "local_model_generation_failed",
                    {"reason": str(exc)},
                )
            )


def strip_thinking(text: str) -> str:
    cleaned = _THINKING_RE.sub("", str(text or ""))
    cleaned = _THINKING_MARKER_RE.sub("", cleaned)
    cleaned = _FINAL_PREFIX_RE.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _messages_with_no_think(
    messages: tuple[dict[str, str], ...],
    model_id: str,
    catalog_entry: dict[str, object],
) -> tuple[dict[str, str], ...]:
    copied = tuple(dict(message) for message in messages)
    if not _uses_qwen_non_thinking(model_id, catalog_entry):
        return copied
    mutable = [dict(message) for message in copied]
    system_seen = False
    for message in mutable:
        if message.get("role") == "system":
            system_seen = True
            message["content"] = _append_once(
                _append_once(str(message.get("content") or ""), _NO_THINK_DIRECTIVE),
                _NO_THINK_RULE,
            )
            break
    if not system_seen:
        mutable.insert(
            0,
            {
                "role": "system",
                "content": f"{_NO_THINK_DIRECTIVE}\n{_NO_THINK_RULE}",
            },
        )
    for message in reversed(mutable):
        if message.get("role") == "user":
            message["content"] = _append_once(
                str(message.get("content") or ""),
                _NO_THINK_DIRECTIVE,
            )
            break
    return tuple(mutable)


def _uses_qwen_non_thinking(model_id: str, entry: dict[str, object]) -> bool:
    source = " ".join(
        str(value)
        for value in (
            model_id,
            entry.get("id", ""),
            entry.get("display_name", ""),
            entry.get("filename", ""),
        )
    ).lower()
    return ("qwen3" in source or "qwen35" in source) and "qwen2.5" not in source


def _append_once(content: str, addition: str) -> str:
    if addition in content:
        return content
    return f"{content.strip()}\n\n{addition}".strip()
