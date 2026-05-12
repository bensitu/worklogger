import os
import sys
import unittest


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_ROOT = os.path.join(PROJECT_ROOT, "worklogger")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from services.ai_service import MAX_RESPONSE_BYTES, _read_limited_response
from services.ai_chat_session import AiChatSession


class _Response:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self, size=-1):
        if size is None or size < 0:
            return self._payload
        return self._payload[:size]


class AIResponseLimitTests(unittest.TestCase):
    def test_read_limited_response_rejects_oversized_body(self):
        with self.assertRaises(ValueError):
            _read_limited_response(_Response(b"x" * (MAX_RESPONSE_BYTES + 1)))

    def test_read_limited_response_accepts_body_at_limit(self):
        body = b"x" * MAX_RESPONSE_BYTES
        self.assertEqual(_read_limited_response(_Response(body)), body)


class AiChatSessionTests(unittest.TestCase):
    def test_preserves_system_message_and_order(self):
        session = AiChatSession("system", max_messages=5)
        session.add_user_message("hello")
        session.add_assistant_message("hi")

        self.assertEqual(
            session.get_messages(),
            [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
            ],
        )

    def test_trims_old_messages_but_keeps_system_message(self):
        session = AiChatSession("system", max_messages=4)
        for i in range(1, 5):
            session.add_user_message(f"u{i}")
            session.add_assistant_message(f"a{i}")

        messages = session.get_messages()
        self.assertEqual(messages[0], {"role": "system", "content": "system"})
        self.assertEqual(
            messages[1:],
            [
                {"role": "user", "content": "u4"},
                {"role": "assistant", "content": "a4"},
            ],
        )

    def test_budget_trimming_preserves_user_first_order(self):
        session = AiChatSession("system", max_messages=20, token_budget=70)
        for i in range(1, 8):
            session.add_user_message(f"user message {i} " + ("x" * 30))
            session.add_assistant_message(f"assistant message {i} " + ("y" * 30))

        messages = session.get_messages()

        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["role"], "user")
        self.assertLessEqual(AiChatSession.estimate_messages_tokens(messages), 70)

    def test_clear_removes_conversation_messages(self):
        session = AiChatSession("system")
        session.add_user_message("hello")
        session.clear()
        self.assertEqual(
            session.get_messages(),
            [{"role": "system", "content": "system"}],
        )


if __name__ == "__main__":
    unittest.main()

