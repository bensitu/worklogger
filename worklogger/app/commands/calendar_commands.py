"""Calendar command DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from worklogger.app.job_runner import CancellationToken


@dataclass(frozen=True)
class ImportCalendarEventsCommand:
    user_id: int
    source_path: Path
    replace_existing: bool = False
    cancellation: CancellationToken | None = None
