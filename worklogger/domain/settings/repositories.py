"""Settings repository Protocols."""

from __future__ import annotations

from typing import Protocol


class SettingsRepository(Protocol):
    def get(self, user_id: int, key: str, default: str | None = None) -> str | None:
        ...

    def set(self, user_id: int, key: str, value: str) -> None:
        ...

    def delete(self, user_id: int, key: str) -> None:
        ...

