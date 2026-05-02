"""Bounded in-memory AI chat session state."""

from __future__ import annotations

import threading


class AiChatSession:
    """Store OpenAI-compatible chat messages with bounded history."""

    def __init__(
        self,
        system_prompt: str,
        max_messages: int = 20,
        token_budget: int | None = None,
    ):
        if not isinstance(system_prompt, str) or not system_prompt.strip():
            raise ValueError("system_prompt_required")
        if max_messages < 3:
            raise ValueError("max_messages_too_small")
        self._system_message = {
            "role": "system",
            "content": system_prompt.strip(),
        }
        self._max_messages = int(max_messages)
        self._token_budget = token_budget
        self._lock = threading.Lock()
        self._messages: list[dict[str, str]] = [dict(self._system_message)]

    def add_user_message(self, content: str) -> None:
        self._add_message("user", content)

    def add_assistant_message(self, content: str) -> None:
        self._add_message("assistant", content)

    def get_messages(
        self,
        *,
        additional_messages: list[dict[str, str]] | None = None,
        token_budget: int | None = None,
    ) -> list[dict[str, str]]:
        with self._lock:
            messages = [dict(message) for message in self._messages]
        if additional_messages:
            messages.extend(dict(message) for message in additional_messages)
        budget = token_budget if token_budget is not None else self._token_budget
        if budget is not None:
            messages = self._trim_messages_to_budget(messages, int(budget))
        return messages

    def get_messages_within_budget(self, available_tokens: int) -> list[dict[str, str]]:
        return self.get_messages(token_budget=available_tokens)

    def message_count(self) -> int:
        with self._lock:
            return len(self._messages)

    def last_assistant_message(self) -> str | None:
        with self._lock:
            for message in reversed(self._messages):
                if message.get("role") == "assistant":
                    return message.get("content", "")
        return None

    def reset(self) -> None:
        self.clear()

    def clear(self) -> None:
        with self._lock:
            self._messages = [dict(self._system_message)]

    def set_token_budget(self, token_budget: int | None) -> None:
        with self._lock:
            self._token_budget = token_budget
            self._trim()

    def _add_message(self, role: str, content: str) -> None:
        if not isinstance(content, str) or not content.strip():
            raise ValueError("message_content_required")
        with self._lock:
            self._messages.append({"role": role, "content": content.strip()})
            self._trim()

    def _trim(self) -> None:
        self._messages = self._trim_message_pairs(
            self._messages,
            max_messages=self._max_messages,
        )
        if self._token_budget is not None:
            self._messages = self._trim_messages_to_budget(
                self._messages,
                self._token_budget,
            )

    @classmethod
    def _trim_message_pairs(
        cls,
        messages: list[dict[str, str]],
        *,
        max_messages: int,
    ) -> list[dict[str, str]]:
        if len(messages) <= max_messages:
            return [dict(message) for message in messages]
        system = dict(messages[0])
        non_system = [dict(message) for message in messages[1:]]
        max_non_system = max(0, max_messages - 1)
        while len(non_system) > max_non_system:
            remove_count = 2 if len(non_system) >= 2 else 1
            del non_system[:remove_count]
        while non_system and non_system[0].get("role") == "assistant":
            del non_system[0]
        return [system, *non_system]

    @classmethod
    def _trim_messages_to_budget(
        cls,
        messages: list[dict[str, str]],
        token_budget: int,
    ) -> list[dict[str, str]]:
        trimmed = [dict(message) for message in messages]
        while len(trimmed) > 2 and cls.estimate_messages_tokens(trimmed) > token_budget:
            non_system = trimmed[1:]
            remove_count = 2 if len(non_system) >= 2 else 1
            trimmed = [trimmed[0], *non_system[remove_count:]]
            while len(trimmed) > 1 and trimmed[1].get("role") == "assistant":
                del trimmed[1]
        return trimmed

    @classmethod
    def estimate_messages_tokens(cls, messages: list[dict[str, str]]) -> int:
        return sum(cls.estimate_text_tokens(message.get("content", "")) + 4 for message in messages)

    @staticmethod
    def estimate_text_tokens(text: str) -> int:
        # Conservative approximation for English/CJK mixed text without adding
        # tokenizer dependencies to the desktop runtime.
        return max(1, (len(text or "") + 2) // 3)
