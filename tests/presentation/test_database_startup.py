"""Startup recovery confirmations, background state, and user feedback."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from worklogger.app.job_runner import JobHandle
from worklogger.domain.shared.errors import InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result
from tests.job_runner import ImmediateJobRunner
from worklogger.presentation.widgets.database_startup import DatabaseStartupDialog


class DatabaseStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from tests.presentation.qt_support import dispose_test_windows
        self.addCleanup(dispose_test_windows)
        self.handler = Mock(allow_new_database=True)
        self.error = InfrastructureError("database_schema_unsupported", "database_schema_unsupported")
        self.path = Path("example/worklog.db").absolute()

    def dialog(self, runner=None):
        return DatabaseStartupDialog(self.path, self.error, self.handler, job_runner=runner or ImmediateJobRunner())

    def test_cancelled_confirmation_or_file_selection_does_not_change_database(self):
        dialog = self.dialog()
        self.assertTrue(dialog.exit_choice.isChecked())
        self.assertTrue(dialog.action_button.isDefault())
        dialog.new_choice.click()
        self.handler.handle.assert_not_called()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            dialog.action_button.click()
        dialog.restore_choice.click()
        self.assertFalse(dialog.new_choice.isChecked())
        with patch("worklogger.presentation.widgets.database_startup.QFileDialog.getOpenFileName", return_value=("", "")):
            dialog.action_button.click()
        self.handler.handle.assert_not_called()
        dialog.exit_choice.click()
        dialog.show()
        dialog.action_button.click()
        self.assertFalse(dialog.isVisible())

    def test_invalid_backup_keeps_dialog_available_and_success_continues(self):
        dialog = self.dialog()
        self.handler.handle.return_value = Result.failure(ValidationError("startup_backup_invalid", "startup_backup_invalid"))
        dialog._run(self.path.parent / "backup.db")
        self.assertTrue(dialog.status_label.text())
        self.assertFalse(dialog._busy)
        self.assertTrue(dialog.restore_choice.isEnabled())
        self.handler.handle.return_value = Result.success(self.path.parent / "database-recovery" / "retained")
        with patch.object(QMessageBox, "information") as feedback:
            dialog._run(None)
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertIn("database-recovery", feedback.call_args.args[2])

    def test_pending_replacement_cannot_be_closed_and_policy_survives_failure(self):
        self.handler.allow_new_database = False
        callbacks = []
        runner = Mock()
        runner.submit.side_effect = lambda _name, _operation, *, on_complete: callbacks.append(on_complete) or JobHandle("recovery", lambda: None)
        dialog = self.dialog(runner)
        dialog.show()
        dialog._run(self.path.parent / "backup.db")
        self.assertTrue(all(not button.isEnabled() for button in dialog._buttons))
        self.assertTrue(all(not choice.isEnabled() for choice in dialog._choices))
        dialog.reject()
        self.assertTrue(dialog.isVisible())
        callbacks[0](Result.failure(InfrastructureError("startup_recovery_failed", "startup_recovery_failed")))
        self.assertFalse(dialog.new_choice.isEnabled())
        self.assertTrue(dialog.restore_choice.isEnabled())
        dialog.reject()
        self.assertFalse(dialog.isVisible())

    def test_unavailable_directory_opener_keeps_copyable_path(self):
        dialog = self.dialog()
        with patch("worklogger.presentation.widgets.file_location.QDesktopServices.openUrl", return_value=False):
            dialog.location.open_button.click()
        self.assertEqual(dialog.location.path_view.toPlainText(), str(self.path))
        self.assertTrue(dialog.location.path_view.isReadOnly())
        dialog.location.path_view.selectAll()
        self.assertEqual(dialog.location.path_view.textCursor().selectedText(), str(self.path))
        self.assertTrue(dialog.status_label.text())
        self.handler.handle.assert_not_called()

    def test_recovery_composition_finishes_new_database_creation_before_returning(self):
        from worklogger.composition.startup_recovery import recover_startup_database
        from worklogger.infrastructure.database.inspection import validate_database_file
        from worklogger.infrastructure.runtime_config import RuntimeConfiguration

        style, palette = self.app.styleSheet(), self.app.palette()
        context = self.app.property("worklogger_theme_context")
        self.addCleanup(self.app.setProperty, "worklogger_theme_context", context)
        self.addCleanup(self.app.setPalette, palette)
        self.addCleanup(self.app.setStyleSheet, style)
        def execute(dialog):
            dialog.new_choice.click()
            QTimer.singleShot(0, dialog.action_button.click)
            return QDialog.exec(dialog)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "worklog.db"
            path.write_bytes(b"Original incompatible database")
            with (patch("worklogger.composition.startup_recovery.default_database_path", return_value=path),
                  patch("worklogger.composition.startup_recovery.initialize_language"),
                  patch("worklogger.composition.startup_recovery.load_runtime_configuration", return_value=RuntimeConfiguration()),
                  patch.object(DatabaseStartupDialog, "exec", execute),
                  patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Ok),
                  patch.object(QMessageBox, "information")):
                self.assertTrue(recover_startup_database(self.error, []))
            validate_database_file(path)
            preserved = next((path.parent / "database-recovery").glob("*/worklog.db"))
            self.assertEqual(preserved.read_bytes(), b"Original incompatible database")

    def test_startup_assistance_keeps_diagnostics_private_and_retries_only_on_request(self):
        from worklogger.presentation.widgets.startup_error import StartupErrorDialog

        error = InfrastructureError("startup_configuration_invalid", "startup_configuration_invalid",
                                    {"resource": "configuration", "reason": "private diagnostic payload"})
        dialog = StartupErrorDialog(error, database_path=self.path,
            log_path=self.path.parent / "worklogger.log", configuration_path=self.path.parent / "worklogger.config.json")
        dialog.show()
        self.assertTrue(dialog.exit_button.isDefault())
        self.assertEqual(dialog.location.path.name, "worklogger.config.json")
        dialog.copy_button.click()
        copied = self.app.clipboard().text()
        self.assertIn("startup_configuration_invalid", copied)
        self.assertIn(str(self.path), copied)
        self.assertNotIn("private diagnostic payload", copied)
        self.assertTrue(dialog.isVisible())
        dialog.retry_button.click()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.handler.handle.assert_not_called()
