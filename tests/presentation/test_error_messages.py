"""Translated user feedback without internal error codes or exception details."""

import ast
import logging
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.i18n.catalog_tools import LANGUAGES, LOCALES_ROOT, read_po_entries
from worklogger.domain.shared.errors import CancellationError, InfrastructureError
from worklogger.infrastructure.i18n import _, set_language
from worklogger.presentation.errors import display_error_code, display_error_message


class ErrorMessageTests(unittest.TestCase):
    def tearDown(self):
        set_language("en_US")

    def test_cancellation_is_neutral_and_does_not_log_an_error(self):
        with patch("worklogger.presentation.errors.LOGGER.error") as error_log:
            for code in ("auth_cancelled", "job_cancelled", "ai_rewrite_cancelled"):
                self.assertEqual(display_error_message(CancellationError(code, code)), "Operation cancelled.")
        error_log.assert_not_called()

    def test_real_errors_retain_diagnostic_codes_in_logs(self):
        with patch.object(logging.getLogger(), "handlers", [logging.NullHandler()]), \
             self.assertLogs("worklogger.presentation.errors", level=logging.ERROR) as logs:
            text = display_error_message(InfrastructureError("update_check_failed", "update_check_failed"))
        self.assertEqual(logs.records[0].error_code, "update_check_failed")
        self.assertIn("network connection", text)

    def test_unknown_errors_never_expose_codes_messages_or_private_details(self):
        for language in LANGUAGES:
            set_language(language)
            text = display_error_message(InfrastructureError("unexpected_storage_failure",
                "Exception: private account or path", {"reason": "private diagnostic"}))
            self.assertEqual(text, _("The operation could not be completed. Please try again."))
            self.assertNotIn("unexpected_storage_failure", text)
            self.assertNotIn("private", text)

    def test_all_mapped_messages_have_complete_catalog_translations(self):
        path = Path(__file__).resolve().parents[2] / "worklogger/presentation/errors.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        codes = {node.value.value for node in ast.walk(tree)
                 if isinstance(node, ast.MatchValue) and isinstance(node.value, ast.Constant)}
        for language in LANGUAGES:
            set_language(language)
            catalog = read_po_entries(LOCALES_ROOT / language / "LC_MESSAGES/messages.po")
            for code in codes:
                message = display_error_code(code)
                with self.subTest(language=language, code=code):
                    self.assertTrue(message)
                    self.assertNotEqual(message, code)
                    self.assertNotIn("_", message)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_":
                    key = node.args[0].value
                    self.assertTrue(catalog[key], (language, key))

    def test_previews_do_not_log_errors(self):
        with patch("worklogger.presentation.errors.LOGGER.error") as error_log:
            self.assertIn("HH:mm", display_error_code("time_range_invalid"))
        error_log.assert_not_called()

    def test_missing_error_still_has_visible_feedback(self):
        self.assertEqual(display_error_message(None), "Unknown error")


if __name__ == "__main__":
    unittest.main()
