"""Automatic backup startup delays and manual transfer availability."""

import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QWidget

from worklogger.domain.cloud_backup import BackupConfiguration, BackupCredentials, BackupOverview, LocalBackupOverview
from worklogger.app.use_cases.cloud_backups import BackupTransfer
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result
from tests.job_runner import ImmediateJobRunner
from worklogger.presentation.settings.sections.cloud_backup import CloudBackupPanel
from worklogger.presentation.settings.workflows.cloud_backup import CloudBackupWorkflow


class CloudBackupWorkflowTests(unittest.TestCase):
    def test_successful_restore_reloads_application_after_panel_destruction(self):
        from shiboken6 import delete
        workflow = self.workflow(86400)
        handler = Mock()
        workflow.set_restore_handler(handler)
        panel = CloudBackupPanel(self.owner)
        callbacks = []
        workflow._run = lambda operation, *, callback: callbacks.append(callback) or True
        workflow._restore(panel, lambda: Result.success(None))
        delete(panel)
        with patch.object(QMessageBox, "information") as message:
            callbacks[0](Result.success(BackupTransfer("", "recovery.wlbackup")))
        handler.assert_called_once()
        message.assert_not_called()

    def test_automatic_settings_refresh_reports_failure_without_interrupting_the_user(self):
        workflow = self.workflow(86400)
        workflow._notify = Mock()
        self.service.settings.return_value = Result.failure(ValidationError("cloud_configuration_invalid", "cloud_configuration_invalid"))
        workflow.reload(automatic=True)
        workflow._notify.assert_not_called()
        self.assertFalse(workflow._busy)

    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.clock = self.enterContext(patch("worklogger.presentation.settings.workflows.cloud_backup.monotonic", return_value=100))
        self.single_shot = self.enterContext(patch("worklogger.presentation.settings.workflows.cloud_backup.QTimer.singleShot"))
        self.service = Mock()
        self.service.settings.return_value = Result.success((
            BackupConfiguration(endpoint="https://storage.example", schedule="daily"), BackupCredentials(), {}))
        self.service.upload.return_value = Result.success(None)
        self.service.record_failure.return_value = Result.success(None)
        self.service.overview.return_value = Result.success(BackupOverview((), "local-digest", False, False))
        self.owner = QWidget()
        self.owner.entry_panel = SimpleNamespace(is_busy=False)
        self.owner.reports_page = SimpleNamespace(is_busy=False)
        self.owner.has_unsaved_changes = False
        self.addCleanup(self.owner.deleteLater)

    def workflow(self, delay, **options):
        workflow = CloudBackupWorkflow(self.service, startup_delay_seconds=delay, job_runner=ImmediateJobRunner(), **options)
        workflow.start(self.owner)
        self.addCleanup(workflow._timer.stop)
        return workflow

    def test_startup_defers_settings_load_and_due_backup_for_configured_seconds(self):
        workflow = self.workflow(17)
        self.service.settings.assert_not_called()
        self.service.upload.assert_not_called()
        milliseconds, _, callback = self.single_shot.call_args.args
        self.assertEqual(milliseconds, 17000)
        workflow.reload()
        self.service.upload.assert_not_called()
        self.clock.return_value = 116.99
        workflow._tick()
        self.service.upload.assert_not_called()
        self.clock.return_value = 117
        callback()
        self.service.upload.assert_called_once_with()

    def test_invalid_saved_backup_time_does_not_stop_scheduling(self):
        configuration, credentials, _state = self.service.settings.return_value.value
        self.service.settings.return_value = Result.success((configuration, credentials, {"last_success": "invalid"}))
        workflow = self.workflow(0)
        workflow.reload()
        self.service.upload.assert_called_once_with()
        self.assertFalse(workflow._busy)

    def test_automatic_backups_wait_for_busy_views_even_after_startup_delay(self):
        workflow = self.workflow(0)
        self.owner.entry_panel.is_busy = True
        workflow.reload()
        self.service.upload.assert_not_called()
        self.owner.entry_panel.is_busy = False
        self.owner.reports_page.is_busy = True
        workflow._tick()
        self.service.upload.assert_not_called()
        self.owner.reports_page.is_busy = False
        workflow._tick()
        self.service.upload.assert_called_once_with()

    def test_manual_upload_is_available_during_the_startup_delay(self):
        workflow = self.workflow(86400)
        panel = CloudBackupPanel(self.owner)
        workflow.bind(panel)
        self.service.upload.assert_not_called()
        with patch("worklogger.presentation.settings.workflows.cloud_backup.BackupTransferDialog") as dialog_factory:
            dialog_factory.return_value.exec.return_value = QDialog.DialogCode.Accepted
            dialog_factory.return_value.force.isChecked.return_value = False
            self.assertTrue(panel.upload_button.isEnabled())
            panel.upload_button.click()
        self.service.upload.assert_called_once_with(expected_revision="", force=False)

    def test_unsaved_fields_disable_transfers_and_failed_save_preserves_the_draft(self):
        workflow = self.workflow(86400)
        workflow._notify = Mock()
        panel = CloudBackupPanel(self.owner)
        workflow.bind(panel)
        panel.endpoint.setText("https://changed-storage.example")
        self.assertFalse(panel.upload_button.isEnabled())
        self.assertFalse(panel.test_button.isEnabled())
        self.assertFalse(panel.restore_button.isEnabled())
        self.service.configure.return_value = Result.failure(ValidationError("cloud_credentials_invalid", "cloud_credentials_invalid"))
        panel.save_button.click()
        self.assertEqual(panel.endpoint.text(), "https://changed-storage.example")
        self.assertTrue(panel.has_unsaved_changes)
        self.service.upload.assert_not_called()

    def test_saved_s3_session_tokens_can_be_cleared_explicitly(self):
        from dataclasses import replace
        configuration = replace(self.service.settings.return_value.value[0], provider="s3", bucket="personal-backups")
        credentials = BackupCredentials("user", "password", "temporary-token", "example-backup-passphrase")
        panel = CloudBackupPanel(self.owner)
        panel.set_configuration(configuration, credentials)
        panel.set_busy(False, configured=True)
        saved = []
        panel.save_requested.connect(lambda configuration, credentials: saved.append(credentials))
        panel.temporary_credentials.setChecked(False)
        panel.save_button.click()
        self.assertEqual(saved[0].session_token, "")
        self.assertEqual(saved[0].password, "password")
        self.assertTrue(panel.session_token.isHidden())

    def test_encryption_switch_preserves_passphrase_and_requires_confirmation_before_saving_without_encryption(self):
        panel = CloudBackupPanel(self.owner)
        configuration = BackupConfiguration(endpoint="https://storage.example")
        credentials = BackupCredentials("user", "password", passphrase="example-backup-passphrase")
        panel.set_configuration(configuration, credentials)
        panel.set_busy(False, configured=True)
        saved = []
        panel.save_requested.connect(lambda configuration, credentials: saved.append((configuration, credentials)))
        self.assertTrue(panel.encrypted.isChecked())
        self.assertFalse(panel.passphrase.isHidden())
        panel.encrypted.click()
        self.assertTrue(panel.passphrase.isHidden())
        self.assertTrue(panel.has_unsaved_changes)
        self.assertFalse(panel.upload_button.isEnabled())
        with patch("PySide6.QtWidgets.QMessageBox.warning", return_value=QMessageBox.StandardButton.No):
            panel.save_button.click()
        self.assertFalse(saved)
        with patch("PySide6.QtWidgets.QMessageBox.warning", return_value=QMessageBox.StandardButton.Yes):
            panel.save_button.click()
        self.assertFalse(saved[0][0].encrypted)
        self.assertEqual(saved[0][1].passphrase, credentials.passphrase)
        panel.encrypted.click()
        self.assertFalse(panel.passphrase.isHidden())

    def test_automatic_failures_are_reported_and_backoff_without_repeated_notifications(self):
        workflow = self.workflow(0)
        workflow._notify = Mock()
        self.service.upload.return_value = Result.failure(ValidationError("cloud_connection_failed", "cloud_connection_failed"))
        workflow.reload()
        self.assertEqual(self.service.upload.call_count, 1)
        workflow._tick()
        self.assertEqual(self.service.upload.call_count, 1)
        self.clock.return_value = 401
        workflow._tick()
        self.assertEqual(self.service.upload.call_count, 2)
        workflow._notify.assert_called_once()
        self.assertEqual(self.service.record_failure.call_count, 2)
        self.service.upload.return_value = Result.success(None)
        self.clock.return_value = 1002
        workflow._tick()
        self.assertEqual(self.service.upload.call_count, 3)
        self.assertEqual(workflow._failures, 0)

    def test_confirmation_blocks_automatic_uploads_and_local_recovery_requires_no_cloud_request(self):
        workflow = self.workflow(17)
        workflow.set_restore_handler(Mock())
        panel = CloudBackupPanel(self.owner)
        workflow.bind(panel)
        self.clock.return_value = 117
        self.service.preview_local.return_value = Result.success(LocalBackupOverview("local", "archive"))
        self.service.restore_local.return_value = Result.success(BackupTransfer("", "recovery-copy.wlbackup"))
        with patch("worklogger.presentation.settings.workflows.cloud_backup.QFileDialog.getOpenFileName", return_value=("local.wlbackup", "")), \
                patch("worklogger.presentation.settings.workflows.cloud_backup.BackupTransferDialog") as dialog_factory, \
                patch("worklogger.presentation.settings.workflows.cloud_backup.QMessageBox.information"):
            def confirm():
                workflow._tick()
                self.service.upload.assert_not_called()
                return QDialog.DialogCode.Accepted
            dialog_factory.return_value.exec.side_effect = confirm
            dialog_factory.return_value.passphrase.text.return_value = "recovery-passphrase"
            panel.local_restore_button.click()
        self.service.restore_local.assert_called_once_with("local.wlbackup", expected_local_digest="local",
            expected_archive_digest="archive", passphrase="recovery-passphrase")
        workflow._restore_handler.assert_called_once()
        self.service.overview.assert_not_called()

    def test_custom_check_interval_and_retry_bounds_control_automatic_retries(self):
        workflow = self.workflow(0, check_interval_seconds=17, retry_initial_seconds=7, retry_max_seconds=10)
        workflow._notify = Mock()
        self.service.upload.return_value = Result.failure(ValidationError("cloud_connection_failed", "cloud_connection_failed"))
        self.assertEqual(workflow._timer.interval(), 17000)
        workflow.reload()
        self.assertEqual(workflow._retry_at, 107)
        self.clock.return_value = 106
        workflow._tick()
        self.assertEqual(self.service.upload.call_count, 1)
        self.clock.return_value = 107
        workflow._tick()
        self.assertEqual(self.service.upload.call_count, 2)
        self.assertEqual(workflow._retry_at, 117)
        self.clock.return_value = 117
        workflow._tick()
        self.assertEqual(workflow._retry_at, 127)

    def test_restore_does_not_open_a_progress_window_while_another_operation_is_running(self):
        workflow = self.workflow(17)
        workflow._busy = True
        operation = Mock()
        with patch("worklogger.presentation.settings.workflows.cloud_backup.RestoreProgressDialog") as progress:
            workflow._restore(self.owner, operation)
        progress.assert_not_called()
        operation.assert_not_called()
