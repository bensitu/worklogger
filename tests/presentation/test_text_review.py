from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from worklogger.app.job_runner import CancellationToken, JobHandle
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result
from worklogger.presentation.text_review import TextReviewTask


class DeferredRunner:
    def __init__(self):
        self.jobs = []
        self.cancelled = []

    def submit(self, name, operation, *, on_complete):
        self.jobs.append((operation, on_complete))
        return JobHandle(name, lambda: self.cancelled.append(name))

    def complete(self, index):
        operation, callback = self.jobs[index]
        callback(operation(CancellationToken()))


class TextReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.owner = QWidget()
        self.runner = DeferredRunner()
        self.task = TextReviewTask(self.owner, job_runner=self.runner)
        self.addCleanup(self.owner.deleteLater)
        self.addCleanup(self.task.cancel)

    def test_review_uses_edited_source_and_instructions_and_applies_only_confirmed_text(self):
        calls, completed = [], []
        def operation(source, instructions, token):
            calls.append((source, instructions))
            return Result.success("Revised " + source)
        self.task.run_review("rewrite_note", "Original", operation, available=lambda: True, on_complete=completed.append)
        self.assertIsNone(self.task.review_dialog)
        self.assertEqual(completed, [])
        self.runner.complete(0)
        dialog = self.task.review_dialog
        self.assertEqual(dialog.source_edit.toPlainText(), "Original")
        self.assertEqual(dialog.result_edit.toPlainText(), "Revised Original")
        self.assertEqual(completed, [])
        self.assertTrue(self.task.is_running)
        dialog.source_edit.setPlainText("Edited source")
        dialog.instructions_edit.setPlainText("Use bullet points")
        dialog.retry_button.click()
        self.assertTrue(dialog.isVisible())
        self.assertEqual(dialog.result_stack.currentIndex(), 1)
        self.assertFalse(dialog.use_button.isEnabled())
        self.assertTrue(dialog.result_edit.isReadOnly())
        self.runner.complete(1)
        self.assertEqual(calls[-1], ("Edited source", "Use bullet points"))
        self.assertEqual(dialog.result_stack.currentIndex(), 0)
        self.assertFalse(dialog.result_edit.isReadOnly())
        dialog.result_edit.setPlainText("Manually corrected result")
        dialog.use_button.click()
        self.assertEqual(completed[0].value, "Manually corrected result")
        self.assertFalse(self.task.is_running)

    def test_failed_or_cancelled_regeneration_keeps_last_result_and_close_ignores_late_results(self):
        completed = []
        responses = [Result.success("First result"), Result.failure(ValidationError("ai_request_failed", "ai_request_failed")),
                     Result.success("Cancelled result"), Result.success("Late result")]
        def operation(*_args):
            return responses.pop(0)
        self.task.run_review("rewrite_note", "Original", operation, available=lambda: True, on_complete=completed.append)
        self.runner.complete(0)
        dialog = self.task.review_dialog
        dialog.result_edit.setPlainText("Edited first result")
        dialog.retry_button.click()
        self.runner.complete(1)
        self.assertEqual(dialog.result_edit.toPlainText(), "Edited first result")
        self.assertTrue(dialog.status_label.text().strip())
        self.assertTrue(dialog.use_button.isEnabled())
        dialog.retry_button.click()
        dialog.progress.cancel_button.click()
        self.assertEqual(dialog.result_edit.toPlainText(), "Edited first result")
        dialog.retry_button.click()
        self.task.cancel()
        self.assertFalse(self.task.is_running)
        self.assertEqual(completed[0].error.code, "ai_rewrite_cancelled")
        self.runner.complete(2)
        self.runner.complete(3)
        self.assertEqual(len(completed), 1)
        self.assertIsNone(self.task.review_dialog)

    def test_unavailable_ai_prevents_requests_regeneration_and_acceptance(self):
        completed, enabled = [], [False]
        operation = lambda *_args: Result.success("Result")
        self.task.run_review("rewrite_note", "Original", operation, available=lambda: enabled[0], on_complete=completed.append)
        self.assertEqual(self.runner.jobs, [])
        self.assertFalse(completed[0].ok)
        enabled[0] = True
        self.task.run_review("rewrite_note", "Original", operation, available=lambda: enabled[0], on_complete=completed.append)
        self.runner.complete(0)
        dialog = self.task.review_dialog
        enabled[0] = False
        dialog.accept()
        dialog._regenerate()
        self.assertIs(self.task.review_dialog, dialog)
        self.assertFalse(dialog.use_button.isEnabled())
        self.assertFalse(dialog.retry_button.isEnabled())
        self.assertEqual(len(self.runner.jobs), 1)
        dialog.cancel_button.click()
        self.assertEqual(completed[-1].error.code, "ai_rewrite_cancelled")


if __name__ == "__main__":
    unittest.main()
