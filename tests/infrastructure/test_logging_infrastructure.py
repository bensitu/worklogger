from __future__ import annotations

import logging
from pathlib import Path
import tempfile
import unittest

from worklogger.infrastructure.logging import setup_logging


def _close_worklogger_handlers() -> None:
    root = logging.getLogger()
    for handler in tuple(root.handlers):
        if bool(getattr(handler, "_worklogger_file_handler", False)):
            root.removeHandler(handler)
            handler.close()


class LoggingInfrastructureTests(unittest.TestCase):
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
                logger.error("remember_token_load_failed")
                try:
                    raise ValueError("private exception payload")
                except ValueError:
                    logger.exception("credential_storage_failed")
                logger.error("safe diagnostic")
                for handler in logging.getLogger().handlers:
                    handler.flush()

                content = log_path.read_text(encoding="utf-8")
                self.assertIn("safe diagnostic", content)
                self.assertIn("remember_token_load_failed", content)
                self.assertIn("credential_storage_failed", content)
                self.assertIn("ValueError", content)
                for secret in ("synthetic-secret", "sensitive-value", "private exception payload"):
                    self.assertNotIn(secret, content)
            finally:
                _close_worklogger_handlers()


if __name__ == "__main__":
    unittest.main()
