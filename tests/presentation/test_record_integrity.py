"""Record recovery confirmation and background submission failures."""

import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from tests.presentation.qt_support import dispose_test_windows
from worklogger.app.use_cases.record_integrity import InvalidRecord, RecordInspection
from worklogger.domain.shared.result import Result
from tests.job_runner import ImmediateJobRunner
from worklogger.presentation.widgets.record_integrity import RecordIntegrityDialog


class RecordIntegrityDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.addCleanup(dispose_test_windows)

    def test_recovery_requires_confirmation_and_a_copy_destination(self):
        inspection = RecordInspection((InvalidRecord(42, "2026-10-06"),), "digest")
        model = Mock()
        model.check_records.return_value = Result.success(inspection)
        model.archive_invalid_records.return_value = Result.success(1)
        dialog = RecordIntegrityDialog(model, job_runner=ImmediateJobRunner())
        self.assertEqual(dialog.tree.topLevelItem(0).text(0), "42")
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.No):
            dialog.recover()
        model.archive_invalid_records.assert_not_called()
        changed = []
        dialog.records_changed.connect(lambda: changed.append(True))
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Yes), \
                patch("worklogger.presentation.widgets.record_integrity.QFileDialog.getSaveFileName",
                      return_value=("recovery.json", "JSON (*.json)")):
            dialog.recover()
        model.archive_invalid_records.assert_called_once_with(inspection, Path("recovery.json"))
        self.assertEqual(changed, [True])
        self.assertFalse(dialog.recover_button.isEnabled())

    def test_submission_failure_releases_controls_and_allows_retry(self):
        runner = Mock()
        runner.submit.side_effect = RuntimeError("Closed runner")
        model = Mock()
        model.check_records.return_value = Result.success(RecordInspection((), "digest"))
        dialog = RecordIntegrityDialog(model, job_runner=runner)
        self.assertTrue(dialog.refresh_button.isEnabled())
        self.assertTrue(dialog.status.text())
        dialog._runner = ImmediateJobRunner()
        dialog.refresh()
        self.assertEqual(dialog.tree.topLevelItemCount(), 0)
        self.assertFalse(dialog.recover_button.isEnabled())
