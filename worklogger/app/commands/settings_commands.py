"""Settings command DTOs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SetSettingCommand:
    user_id: int
    key: str
    value: str


@dataclass(frozen=True)
class SetActiveLocalModelCommand:
    user_id: int
    model_id: str | None

