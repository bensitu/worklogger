"""Supported actions when the main window is closed."""

from __future__ import annotations

from enum import Enum


class WindowCloseAction(str, Enum):
    EXIT = "exit"
    HIDE = "hide"

    @classmethod
    def from_setting(cls, value: str | None) -> WindowCloseAction:
        try:
            return cls(value if value is not None else cls.HIDE.value)
        except ValueError:
            return cls.EXIT
