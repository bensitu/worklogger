"""Data-portability command DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ImportWorkLogsCsvCommand:
    user_id: int
    source_path: Path

