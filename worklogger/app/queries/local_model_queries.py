"""Local model query DTOs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ListLocalModelsQuery:
    user_id: int
