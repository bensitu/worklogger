"""Cancellable presentation requests with stale-result protection."""

from PySide6.QtCore import QObject, Signal, QCoreApplication
from shiboken6 import isValid
from worklogger.domain.shared.errors import CancellationError, InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.presentation.job_runner import QtJobRunner


class TextProcessingTask(QObject):
    started = Signal()
    finished = Signal()

    def __init__(self, parent=None, *, job_runner=None):
        super().__init__(parent)
        self._runner = job_runner or QtJobRunner(QCoreApplication.instance())
        self._version, self._running = 0, False
        self._handle, self._callback = None, None

    @property
    def is_running(self):
        return self._running

    def run(self, name, operation, *, on_complete):
        if self._running:
            return False
        self._version += 1
        version = self._version
        self._running, self._callback = True, on_complete
        self.started.emit()
        if not self._running or version != self._version:
            return True
        def complete(result):
            if not isValid(self) or not self._running or version != self._version:
                return
            callback = self._callback
            self._running, self._handle, self._callback = False, None, None
            self.finished.emit()
            callback(result)
        try:
            handle = self._runner.submit(name, operation, on_complete=complete)
            if self._running and version == self._version:
                self._handle = handle
        except Exception:
            complete(Result.failure(InfrastructureError("ai_request_failed", "ai_request_failed")))
        return True

    def cancel(self):
        if not self._running:
            return
        self._version += 1
        if self._handle is not None:
            self._handle.cancel()
        callback = self._callback
        self._running, self._handle, self._callback = False, None, None
        self.finished.emit()
        callback(Result.failure(CancellationError("ai_rewrite_cancelled", "ai_rewrite_cancelled")))
