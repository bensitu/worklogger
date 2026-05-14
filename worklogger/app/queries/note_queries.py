"""Note query DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class GetDailyNoteQuery:
    user_id: int
    day: date
