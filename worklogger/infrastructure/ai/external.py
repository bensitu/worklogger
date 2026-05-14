"""OpenAI-compatible AI gateway adapter."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from worklogger.app.ports import AIRequest, AIResponse
from worklogger.domain.shared.errors import InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result


UrlOpen = Callable[..., object]


class OpenAICompatibleGateway:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        provider: str = "openai-compatible",
        max_response_bytes: int = 512 * 1024,
        retries: int = 1,
        opener: UrlOpen | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._provider = provider
        self._max_response_bytes = max_response_bytes
        self._retries = max(0, int(retries))
        self._opener = opener or urlopen

    def generate(self, request: AIRequest) -> Result[AIResponse]:
        if not str(self._api_key or "").strip():
            return Result.failure(ValidationError("ai_api_key_required", "ai_api_key_required"))
        payload = json.dumps(
            {
                "model": request.model,
                "messages": list(request.messages),
            }
        ).encode("utf-8")
        url_request = Request(
            f"{self._base_url}/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "User-Agent": "WorkLogger",
            },
            method="POST",
        )
        last_error: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                with self._opener(url_request, timeout=request.timeout_seconds) as response:
                    raw = response.read(self._max_response_bytes + 1)
                if len(raw) > self._max_response_bytes:
                    raise ValueError("ai_response_too_large")
                data = json.loads(raw.decode("utf-8"))
                text = _extract_text(data)
                if not text:
                    raise ValueError("ai_response_empty")
                return Result.success(AIResponse(text=text, provider=self._provider))
            except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < self._retries:
                    time.sleep(min(0.25 * (attempt + 1), 1.0))
        return Result.failure(
            InfrastructureError(
                "ai_request_failed",
                "ai_request_failed",
                {"reason": str(last_error) if last_error else ""},
            )
        )


def _extract_text(data: object) -> str:
    if not isinstance(data, dict):
        return ""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if isinstance(message, dict):
        return str(message.get("content") or "").strip()
    return str(first.get("text") or "").strip()

