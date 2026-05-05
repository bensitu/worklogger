import io
import os
import sys
import unittest
import urllib.error
from unittest.mock import Mock, patch


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_ROOT = os.path.join(PROJECT_ROOT, "worklogger")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from services.ai_service import _CallbackInvoker, _read_json_with_retries


class _Response:
    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def read(self, size=-1):
        if size is None or size < 0:
            return self._payload
        return self._payload[:size]


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://example.invalid/chat/completions",
        code,
        f"HTTP {code}",
        hdrs={},
        fp=io.BytesIO(b'{"error":{"message":"failed"}}'),
    )


class AIRetryTests(unittest.TestCase):
    def test_retryable_http_error_retries_then_succeeds(self):
        plans = [
            _http_error(500),
            _Response(b'{"choices":[{"message":{"content":"OK"}}]}'),
        ]

        def _urlopen(_req, timeout):
            del timeout
            plan = plans.pop(0)
            if isinstance(plan, Exception):
                raise plan
            return plan

        with patch("services.ai_service.urllib.request.urlopen", side_effect=_urlopen), \
             patch("services.ai_service.time.sleep", return_value=None) as sleep:
            data = _read_json_with_retries(
                Mock(),
                timeout=60,
                is_cancelled=lambda: False,
                on_wait=lambda: None,
            )

        self.assertEqual(data["choices"][0]["message"]["content"], "OK")
        self.assertEqual(sleep.call_count, 1)

    def test_non_retryable_http_error_is_propagated_immediately(self):
        with patch(
            "services.ai_service.urllib.request.urlopen",
            side_effect=_http_error(401),
        ), patch("services.ai_service.time.sleep", return_value=None) as sleep:
            with self.assertRaises(urllib.error.HTTPError):
                _read_json_with_retries(
                    Mock(),
                    timeout=60,
                    is_cancelled=lambda: False,
                    on_wait=lambda: None,
                )

        self.assertEqual(sleep.call_count, 0)


class AICallbackInvokerTests(unittest.TestCase):
    def test_detach_drops_ui_callback_references(self):
        calls: list[str] = []
        invoker = _CallbackInvoker(
            lambda _text: calls.append("done"),
            lambda _short, _detail: calls.append("error"),
            lambda _status: calls.append("status"),
        )

        invoker.detach_callbacks()
        invoker._on_done("ok")
        invoker._on_error("short", "detail")
        invoker._on_status("status")

        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()

