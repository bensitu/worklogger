"""Local model command DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from worklogger.app.job_runner import CancellationToken
from collections.abc import Callable
from worklogger.domain.local_model.models import DownloadProgress


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
    cancellation: CancellationToken | None = None
    progress: Callable[[DownloadProgress], None] | None = None


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
