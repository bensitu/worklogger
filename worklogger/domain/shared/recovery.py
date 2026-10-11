"""Available choices for an interrupted database replacement."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RestoreRecoveryChoices:
    rollback_available: bool
    restored_available: bool
