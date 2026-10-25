"""Serialized dialog operations with owner-scoped completion and error recovery."""

from PySide6.QtCore import QObject

from worklogger.app.use_cases._errors import infrastructure_failure
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import _
from worklogger.presentation.job_runner import owned_callback


class DialogOperations(QObject):
    def __init__(self, owner, status_label, *, job_runner=None):
        super().__init__(owner)
        self._owner, self._status = owner, status_label
        self._runner = job_runner
        self.is_running = False

    def run(self, name, operation, completed, *, error_code):
        if self.is_running:
            return False
        self.is_running = True
        self._owner.setEnabled(False)
        self._status.setText(_("Loading..."))
        successful = True

        def execute():
            try:
                return operation()
            except Exception as error:
                return Result.failure(infrastructure_failure(error_code, error, logger_name=__name__))

        def complete(result):
            nonlocal successful
            self.is_running = False
            successful = result.ok
            self._owner.setEnabled(True)
            completed(result)

        if self._runner is None:
            complete(execute())
        else:
            try:
                self._runner.submit(name, lambda _token: execute(), on_complete=owned_callback(self, complete))
            except Exception as error:
                complete(Result.failure(infrastructure_failure(error_code, error, logger_name=__name__)))
        return successful
