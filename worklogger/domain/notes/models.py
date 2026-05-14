"""Notes domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DailyNote:
    user_id: int
    day: date
    content: str = ""
