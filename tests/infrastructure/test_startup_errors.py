"""Storage failure classification preserves database recovery and safe diagnostics."""

import errno
import sqlite3
import unittest

from worklogger.infrastructure.startup_errors import startup_error


class StartupErrorTests(unittest.TestCase):
    def test_sqlite_and_operating_system_failures_have_actionable_categories(self):
        for code, expected in (
            (sqlite3.SQLITE_READONLY, "startup_storage_readonly"),
            (sqlite3.SQLITE_READONLY | (1 << 8), "startup_storage_readonly"),
            (sqlite3.SQLITE_FULL, "startup_storage_full"),
            (sqlite3.SQLITE_BUSY, "startup_storage_busy"),
            (sqlite3.SQLITE_LOCKED, "startup_storage_busy"),
            (sqlite3.SQLITE_CANTOPEN, "startup_storage_unavailable"),
            (sqlite3.SQLITE_CORRUPT, "database_corrupt"),
        ):
            with self.subTest(code=code):
                error = sqlite3.OperationalError("private exception message")
                error.sqlite_errorcode = code
                result = startup_error(error)
                self.assertEqual(result.code, expected)
                self.assertNotIn("private exception message", repr(result))
        for error, expected in (
            (PermissionError(), "startup_permission_denied"),
            (OSError(errno.ENOSPC, ""), "startup_storage_full"),
            (OSError(errno.EROFS, ""), "startup_storage_readonly"),
        ):
            self.assertEqual(startup_error(error).code, expected)

    def test_schema_and_interrupted_restore_errors_keep_their_recovery_paths(self):
        for code in ("database_schema_unsupported", "startup_recovery_pending", "restore_pending"):
            self.assertEqual(startup_error(ValueError(code)).code, code)
        error = startup_error(OSError("private log content"), fallback="startup_logging_failed", resource="logging")
        self.assertEqual(error.code, "startup_logging_failed")
        self.assertEqual(error.details["resource"], "logging")
