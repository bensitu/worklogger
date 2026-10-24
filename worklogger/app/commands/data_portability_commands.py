"""Data-portability command DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from worklogger.app.job_runner import CancellationToken


@dataclass(frozen=True)
class ImportWorkLogsCsvCommand:
    user_id: int
    source_path: Path
    overwrite_existing: bool = False
    replace_dates: bool = False
    cancellation: CancellationToken | None = None

