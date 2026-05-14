"""Update-check use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from worklogger.app.queries.update_queries import CheckForUpdatesQuery
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result


class UpdateCheckerProtocol(Protocol):
    def check_latest_version(self, current_version: str) -> Result[str | None]:
        ...


@dataclass(frozen=True)
class UpdateCheckResult:
    current_version: str
    latest_version: str | None
    update_available: bool


class CheckForUpdatesHandler:
    def __init__(self, checker: UpdateCheckerProtocol) -> None:
        self._checker = checker

    def handle(self, query: CheckForUpdatesQuery) -> Result[UpdateCheckResult]:
        result = self._checker.check_latest_version(query.current_version)
        if not result.ok:
            return Result.failure(result.error or InfrastructureError("update_check_failed", "update_check_failed"))
        latest = result.value
        return Result.success(
            UpdateCheckResult(
                current_version=query.current_version,
                latest_version=latest,
                update_available=latest is not None,
            )
        )

