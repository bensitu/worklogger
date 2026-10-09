"""Explicit, atomic export of a user-requested account credential."""

from pathlib import Path

from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.files import atomic_destination


def export_credential(destination: Path, credential: str) -> Result[Path]:
    try:
        if not credential:
            raise ValueError("credential_required")
        with atomic_destination(destination) as temporary:
            temporary.write_text(credential + "\n", encoding="utf-8")
        return Result.success(destination)
    except (OSError, ValueError):
        return Result.failure(InfrastructureError("credential_export_failed", "credential_export_failed"))
