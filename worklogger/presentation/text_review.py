"""Reviewable text requests that never apply unconfirmed model output."""

from PySide6.QtWidgets import QDialog
from shiboken6 import isValid

from worklogger.domain.shared.errors import CancellationError, ValidationError
from worklogger.domain.shared.result import Result
from worklogger.presentation.processing import TextProcessingTask


class TextReviewTask(TextProcessingTask):
    def __init__(self, parent=None, *, job_runner=None):
        super().__init__(parent, job_runner=job_runner)
        self.review_dialog = None

    @property
    def is_running(self):
        return super().is_running or self.review_dialog is not None

    def run_review(self, name, source, operation, *, available, instructions="", on_complete):
        if self.is_running:
            return False
        if not available():
            on_complete(Result.failure(ValidationError("ai_rewrite_not_configured", "ai_rewrite_not_configured")))
            return False

        def generated(result):
            if not result.ok or result.value is None:
                on_complete(result)
                return
            if not available():
                on_complete(Result.failure(ValidationError("ai_rewrite_not_configured", "ai_rewrite_not_configured")))
                return
            from worklogger.presentation.widgets.text_review import TextReviewDialog
            dialog = TextReviewDialog(source, result.value, operation=operation, available=available,
                                      instructions=instructions, job_runner=self._runner, parent=self.parent())
            self.review_dialog = dialog

            def reviewed(code):
                if not isValid(self) or self.review_dialog is not dialog:
                    return
                self.review_dialog = None
                value = (Result.success(dialog.result_edit.toPlainText()) if code == QDialog.DialogCode.Accepted else
                         Result.failure(CancellationError("ai_rewrite_cancelled", "ai_rewrite_cancelled")))
                dialog.deleteLater()
                on_complete(value)
            dialog.finished.connect(reviewed)
            dialog.open()

        return super().run(f"ai_{name}", lambda token: operation(source, instructions, token), on_complete=generated)

    def cancel(self):
        if self.review_dialog is not None:
            self.review_dialog.reject()
            return
        super().cancel()
