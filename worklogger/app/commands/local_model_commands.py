"""Local model command DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RefreshLocalModelCatalogCommand:
    user_id: int


@dataclass(frozen=True)
class ImportLocalModelCommand:
    user_id: int
    source_path: Path | str


@dataclass(frozen=True)
class DownloadLocalModelCommand:
    user_id: int
    model_id: str


@dataclass(frozen=True)
class VerifyLocalModelCommand:
    user_id: int
    model_id: str


@dataclass(frozen=True)
class SelectLocalModelCommand:
    user_id: int
    model_id: str | None


@dataclass(frozen=True)
class DeleteLocalModelCommand:
    user_id: int
    model_id: str
