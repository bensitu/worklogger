"""Explicit, atomic export of a user-requested recovery key."""

from pathlib import Path

from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.files import atomic_destination


def export_recovery_key(destination: Path, recovery_key: str) -> Result[Path]:
    try:
        if not recovery_key:
            raise ValueError("recovery_key_required")
        with atomic_destination(destination) as temporary:
            temporary.write_text(recovery_key + "\n", encoding="utf-8")
        return Result.success(destination)
    except (OSError, ValueError):
        return Result.failure(InfrastructureError("recovery_key_export_failed", "recovery_key_export_failed"))
