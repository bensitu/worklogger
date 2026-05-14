"""Settings query DTOs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GetSettingQuery:
    user_id: int
    key: str
    default: str | None = None
