"""Local model query DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from worklogger.app.job_runner import CancellationToken


@dataclass(frozen=True)
class ListLocalModelsQuery:
    user_id: int
    cancellation: CancellationToken | None = None
