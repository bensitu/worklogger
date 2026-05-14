"""Note command DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class SaveDailyNoteCommand:
    user_id: int
    day: date
    content: str
