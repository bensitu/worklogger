"""Calendar command DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ImportCalendarEventsCommand:
    user_id: int
    source_path: Path
    replace_existing: bool = False
