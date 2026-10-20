"""Explicit credential exports and platform-bound key protection."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from worklogger.infrastructure.security.credential_export import export_credential


class CredentialExportTests(unittest.TestCase):
    def test_export_is_explicit_and_failed_replacement_preserves_existing_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credential.txt"
            self.assertTrue(export_credential(path, "synthetic-recovery-key").ok)
            self.assertEqual(path.read_text(encoding="utf-8"), "synthetic-recovery-key\n")
            self.assertFalse(export_credential(path, "").ok)
            with patch("worklogger.infrastructure.security.credential_export.atomic_destination", side_effect=OSError("private details")):
                result = export_credential(path, "replacement")
            self.assertEqual(result.error.code, "credential_export_failed")
            self.assertEqual(result.error.details, {})
            self.assertEqual(path.read_text(encoding="utf-8"), "synthetic-recovery-key\n")

    @unittest.skipUnless(sys.platform == "win32", "Windows Data Protection API is required")
    def test_windows_protection_round_trips_bytes_and_rejects_modified_content(self):
        from worklogger.infrastructure.security.windows_protection import protect, unprotect
        original = bytes(range(32))
        protected = protect(original)
        self.assertNotEqual(protected, original)
        self.assertEqual(unprotect(protected), original)
        modified = protected[:-1] + bytes([protected[-1] ^ 1])
        with self.assertRaises(OSError):
            unprotect(modified)
