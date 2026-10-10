"""Cooperative browser authorization requests on the Qt background runner."""

from PySide6.QtCore import QObject, Signal, QCoreApplication
from shiboken6 import isValid
from worklogger.domain.shared.errors import CancellationError, InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.presentation.job_runner import QtJobRunner


class IdentityAuthorizationRequest(QObject):
    started = Signal()
    finished = Signal()

    def __init__(self, parent=None, *, job_runner=None):
        super().__init__(parent)
        self._runner = job_runner or QtJobRunner(QCoreApplication.instance())
        self.is_running = False
        self._handle = None
        self._cancelled = False

    def start(self, operation, *, on_complete):
        if self.is_running:
            return False
        self.is_running, self._cancelled = True, False
        self.started.emit()
        def complete(result):
            if not isValid(self):
                return
            if self._cancelled:
                result = Result.failure(CancellationError("identity_authorization_cancelled", "identity_authorization_cancelled"))
            self.is_running, self._handle = False, None
            self.finished.emit()
            on_complete(result)
        try:
            handle = self._runner.submit("identity_authorization", operation, on_complete=complete)
            if self.is_running:
                self._handle = handle
                if self._cancelled:
                    handle.cancel()
        except Exception:
            complete(Result.failure(InfrastructureError("identity_auth_failed", "identity_auth_failed")))
        return True

    def cancel(self):
        if self.is_running:
            self._cancelled = True
            if self._handle is not None:
                self._handle.cancel()
