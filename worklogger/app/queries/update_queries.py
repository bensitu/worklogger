"""Update query DTOs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CheckForUpdatesQuery:
    current_version: str

