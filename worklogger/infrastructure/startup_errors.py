"""Classify startup failures without exposing exception messages or file contents."""

import errno
import sqlite3

from worklogger.domain.shared.errors import InfrastructureError
from worklogger.infrastructure.database.connection import DatabaseIntegrityError

_DATABASE_ERRORS = frozenset({
    "database_version_unsupported", "database_schema_unsupported", "database_foreign_key_invalid",
    "username_normalization_conflict", "identity_subject_ambiguous", "restore_pending",
    "startup_recovery_pending", "database_record_invalid", "database_record_count_invalid",
    "database_entry_type_unsupported",
})


def startup_error(error: Exception, *, fallback="desktop_runtime_failed", resource="database"):
    code = getattr(error, "sqlite_errorcode", 0) & 0xFF
    name = {
        sqlite3.SQLITE_READONLY: "startup_storage_readonly",
        sqlite3.SQLITE_FULL: "startup_storage_full",
        sqlite3.SQLITE_BUSY: "startup_storage_busy",
        sqlite3.SQLITE_LOCKED: "startup_storage_busy",
        sqlite3.SQLITE_PERM: "startup_permission_denied",
        sqlite3.SQLITE_CANTOPEN: "startup_storage_unavailable",
        sqlite3.SQLITE_IOERR: "startup_storage_unavailable",
    }.get(code, fallback)
    if isinstance(error, DatabaseIntegrityError) or code in {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB}:
        name = "database_corrupt"
    elif isinstance(error, PermissionError):
        name = "startup_permission_denied"
    elif isinstance(error, OSError):
        if error.errno in {errno.ENOSPC, errno.EDQUOT}:
            name = "startup_storage_full"
        elif error.errno == errno.EROFS:
            name = "startup_storage_readonly"
        else:
            name = "startup_storage_unavailable" if resource != "logging" else fallback
    elif isinstance(error, ValueError) and str(error) in _DATABASE_ERRORS:
        name = str(error)
    return InfrastructureError(name, name, {"error_type": type(error).__name__, "resource": resource})
