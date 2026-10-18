"""Explicit database replacement before account authentication."""

from pathlib import Path
from typing import Protocol

from worklogger.app.use_cases._errors import infrastructure_failure
from worklogger.domain.shared.errors import AuthorizationError, ValidationError
from worklogger.domain.shared.result import Result

DATABASE_RECOVERY_ERROR_CODES = frozenset({
    "database_corrupt", "database_version_unsupported", "database_schema_unsupported",
    "database_foreign_key_invalid", "username_normalization_conflict", "identity_subject_ambiguous",
    "database_record_invalid", "database_record_count_invalid", "database_entry_type_unsupported",
    "startup_recovery_pending",
})


class StartupDatabaseStorage(Protocol):
    def replace(self, backup: Path | None) -> Path: ...


class RecoverStartupDatabaseHandler:
    def __init__(self, storage: StartupDatabaseStorage, *, allow_new_database: bool = True):
        self._storage = storage
        self.allow_new_database = allow_new_database

    def handle(self, backup: Path | None = None) -> Result[Path]:
        if backup is None and not self.allow_new_database:
            return Result.failure(AuthorizationError("self_registration_disabled", "self_registration_disabled"))
        try:
            return Result.success(self._storage.replace(backup))
        except (ValueError, FileNotFoundError):
            return Result.failure(ValidationError("startup_backup_invalid", "startup_backup_invalid"))
        except Exception as error:
            return Result.failure(infrastructure_failure("startup_recovery_failed", error, logger_name=__name__))
