"""HTTP request and response contracts for external text generation."""

from __future__ import annotations

from io import BytesIO
import json
import unittest

from worklogger.app.ports import AIRequest
from worklogger.infrastructure.ai.external import OpenAICompatibleGateway


class FakeHttpResponse:
    def __init__(self, payload: dict) -> None:
        self.stream = BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self) -> "FakeHttpResponse":
        return self

    def __exit__(self, *args: object) -> None:
        self.stream.close()

    def read(self, size: int) -> bytes:
        return self.stream.read(size)


class AiGatewayTests(unittest.TestCase):
    def test_openai_compatible_gateway_posts_chat_completion(self) -> None:
        seen: dict[str, object] = {}

        def opener(request: object, timeout: float) -> FakeHttpResponse:
            seen["url"] = request.full_url
            seen["timeout"] = timeout
            seen["body"] = json.loads(request.data.decode("utf-8"))
            return FakeHttpResponse(
                {"choices": [{"message": {"content": "remote answer"}}]}
            )

        gateway = OpenAICompatibleGateway(
            api_key="secret",
            base_url="https://example.test/v1",
            opener=opener,
        )
        result = gateway.generate(
            AIRequest(
                messages=({"role": "user", "content": "hi"},),
                model="model-a",
                timeout_seconds=12,
            )
        )

        self.assertTrue(result.ok)
        assert result.value is not None
        self.assertEqual(result.value.text, "remote answer")
        self.assertEqual(seen["url"], "https://example.test/v1/chat/completions")
        self.assertEqual(seen["body"]["model"], "model-a")
