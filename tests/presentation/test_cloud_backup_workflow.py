"""Automatic backup startup delays and manual transfer availability."""

import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QWidget

from worklogger.domain.cloud_backup import BackupConfiguration, BackupCredentials, BackupOverview
from worklogger.domain.shared.result import Result
from worklogger.presentation.job_runner import ImmediateJobRunner
from worklogger.presentation.settings.sections.cloud_backup import CloudBackupPanel
from worklogger.presentation.settings.workflows.cloud_backup import CloudBackupWorkflow


class CloudBackupWorkflowTests(unittest.TestCase):
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
        self.service.overview.return_value = Result.success(BackupOverview((), "local-digest", False, False))
        self.owner = QWidget()
        self.owner.entry_panel = SimpleNamespace(is_busy=False)
        self.owner.reports_page = SimpleNamespace(is_busy=False)
        self.owner.has_unsaved_changes = False
        self.addCleanup(self.owner.deleteLater)

    def workflow(self, delay):
        workflow = CloudBackupWorkflow(self.service, startup_delay_seconds=delay, job_runner=ImmediateJobRunner())
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
