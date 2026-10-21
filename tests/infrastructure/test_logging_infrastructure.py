from __future__ import annotations

import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from worklogger.infrastructure.logging import setup_logging


def _close_worklogger_handlers() -> None:
    root = logging.getLogger()
    for handler in tuple(root.handlers):
        if bool(getattr(handler, "_worklogger_file_handler", False)):
            root.removeHandler(handler)
            handler.close()


class LoggingInfrastructureTests(unittest.TestCase):
    def test_log_file_symlinks_cannot_redirect_output(self):
        with tempfile.TemporaryDirectory() as directory:
            target, link = Path(directory) / "retained.txt", Path(directory) / "worklogger.log"
            target.write_text("Retained content", encoding="utf-8")
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("Symbolic links are unavailable on this system")
            with self.assertRaises(OSError):
                setup_logging(link)
            self.assertEqual(target.read_text(encoding="utf-8"), "Retained content")
    def setUp(self):
        import sys
        import threading
        self.enterContext(patch.object(sys, "excepthook", sys.excepthook))
        self.enterContext(patch.object(threading, "excepthook", threading.excepthook))
        self.enterContext(patch("worklogger.infrastructure.exception_hooks._previous_hook", sys.excepthook))

    def test_default_log_location_does_not_follow_the_launch_directory(self):
        from worklogger.infrastructure.logging import _resolve_log_path
        from worklogger.infrastructure.database.paths import default_database_path

        with patch.dict("os.environ", {"WORKLOGGER_LOG_PATH": ""}):
            self.assertEqual(_resolve_log_path(None, frozen=False), default_database_path(frozen=False).parent / "worklogger.log")

    def test_setup_logging_writes_rotating_file_without_duplicate_handlers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            try:
                log_path = Path(directory) / "worklogger.log"

                configured = setup_logging(log_path, debug=True)
                setup_logging(log_path, debug=True)
                logging.getLogger("worklogger.test").info("startup_complete")
                for handler in logging.getLogger().handlers:
                    handler.flush()

                self.assertEqual(configured, log_path)
                self.assertTrue(log_path.exists())
                self.assertIn("startup_complete", log_path.read_text(encoding="utf-8"))
                worklogger_handlers = [
                    handler
                    for handler in logging.getLogger().handlers
                    if bool(getattr(handler, "_worklogger_file_handler", False))
                ]
                self.assertEqual(len(worklogger_handlers), 1)
            finally:
                _close_worklogger_handlers()

    def test_setup_logging_filters_sensitive_messages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            try:
                log_path = Path(directory) / "worklogger.log"

                setup_logging(log_path, debug=True)
                logger = logging.getLogger("worklogger.test")
                logger.error("password=synthetic-secret token=sensitive-value")
                logger.error("password=secret containing spaces; request_id=retained")
                logger.error("remember_token_load_failed")
                try:
                    raise ValueError("private exception payload")
                except ValueError:
                    logger.exception("credential_storage_failed")
                logger.error("safe diagnostic")
                logger.error("Invalid numeric value: %d", "private malformed payload")
                from worklogger.app.use_cases._errors import infrastructure_failure
                failure = infrastructure_failure("worklog_save_failed", OSError("private storage payload"), logger_name="worklogger.test")
                self.assertEqual(failure.details, {"reason": "OSError"})
                logger.error('Authorization: Basic encoded-basic-secret')
                logger.error('{"api_key": "json-secret", "password": "escaped\\\"secret"}')
                logger.error("https://user:private-userinfo@example.com/?%74oken=url-secret&code=authorization-secret&request_id=safe-request")
                for handler in logging.getLogger().handlers:
                    handler.flush()

                content = log_path.read_text(encoding="utf-8")
                self.assertIn("safe diagnostic", content)
                self.assertIn("Log message formatting failed", content)
                self.assertNotIn("private malformed payload", content)
                self.assertIn("remember_token_load_failed", content)
                self.assertIn("credential_storage_failed", content)
                self.assertIn("ValueError", content)
                self.assertIn("safe-request", content)
                self.assertIn("request_id=retained", content)
                self.assertNotIn("containing spaces", content)
                self.assertIn("worklog_save_failed: OSError", content)
                self.assertNotIn("private storage payload", content)
                for secret in ("synthetic-secret", "sensitive-value", "private exception payload",
                               "encoded-basic-secret", "json-secret", "escaped", "private-userinfo", "url-secret", "authorization-secret"):
                    self.assertNotIn(secret, content)
            finally:
                _close_worklogger_handlers()

    def test_uncaught_failures_are_logged_without_private_exception_payloads(self):
        import sys
        import threading
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory, patch.object(sys, "excepthook"), patch.object(threading, "excepthook"):
            try:
                path = Path(directory) / "exceptions.log"
                setup_logging(path)
                try:
                    raise ValueError("private exception payload")
                except ValueError as error:
                    sys.excepthook(type(error), error, error.__traceback__)
                    threading.excepthook(SimpleNamespace(exc_type=type(error), exc_value=error, exc_traceback=error.__traceback__))
                for handler in logging.getLogger().handlers:
                    handler.flush()
                content = path.read_text(encoding="utf-8")
                self.assertIn("Unhandled application exception", content)
                self.assertIn("Unhandled thread exception", content)
                self.assertIn("ValueError", content)
                self.assertNotIn("private exception payload", content)
            finally:
                _close_worklogger_handlers()


if __name__ == "__main__":
    unittest.main()
