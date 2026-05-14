"""AI query DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class BuildAiContextQuery:
    user_id: int
    selected_day: date
    period_type: str = "daily"
