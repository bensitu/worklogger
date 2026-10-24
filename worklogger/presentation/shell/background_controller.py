"""Background workflow with asynchronous validation and storage."""

from PySide6.QtCore import QObject, Signal
from shiboken6 import isValid

from worklogger.domain.shared.errors import CancellationError, InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.images.background import prepare_background
from worklogger.presentation.job_runner import shared_job_runner


class BackgroundController(QObject):
    completed = Signal(object)
    busy_changed = Signal(bool)

    def __init__(self, surface, service, *, available=False, job_runner=None):
        super().__init__(surface)
        self._surface, self._service = surface, service
        self.available = bool(available and service is not None)
        self._runner = job_runner
        self._busy = False
        self._disposed = False
        self._version = 0
        self._handle = None
        self._last_result = None
        self._operation = None
        self._pending_options = None
        self._pending_operation = None
        self._prepared_background = None
        surface.destroyed.connect(self.dispose)

    @property
    def is_busy(self):
        return self._busy

    @property
    def last_result(self):
        return self._last_result

    @property
    def is_saving_options(self):
        return self._busy and self._operation == "background_options" and self._pending_operation is None

    def reload(self):
        return self._submit("background_load", self._service.load if self.available else None)

    def import_image(self, source):
        return self._submit("background_import", lambda: self._service.import_image(source))

    def set_options(self, *, enabled, opacity):
        if self.is_saving_options:
            self._pending_options = (enabled, opacity)
            return True
        return self._submit("background_options", lambda: self._service.set_options(enabled=enabled, opacity=opacity))

    def clear(self):
        return self._submit("background_clear", self._service.clear if self.available else None)

    def _submit(self, name, operation):
        if not self.available or self._disposed:
            return False
        if self._busy:
            if self.is_saving_options:
                self._pending_operation = (name, operation)
                self.busy_changed.emit(True)
                return True
            return False
        if self._runner is None:
            self._runner = shared_job_runner()
        self._version += 1
        version = self._version
        self._busy = True
        self._operation = name
        prepared = self._prepared_background
        self.busy_changed.emit(True)
        if self._disposed or version != self._version:
            return False

        def work(token):
            if token.is_cancelled():
                return Result.failure(CancellationError("job_cancelled", "job_cancelled"))
            result = operation()
            if not result.ok:
                return result
            if name == "background_options" and prepared is not None and result.value.image == prepared[0]:
                return Result.success((result.value, prepared[1]))
            return prepare_background(result.value)

        def complete(result):
            if not isValid(self) or not isValid(self._surface) or version != self._version:
                return
            if result.ok:
                state, frame = result.value
                if not frame.isNull():
                    self._prepared_background = (state.image, frame)
                elif state.image is None:
                    self._prepared_background = None
                self._surface.set_background(state, frame)
                result = Result.success(state)
            self._busy, self._handle = False, None
            self._last_result = result
            # Keep intermediate saves from replacing a newer selection in the controls.
            if self._pending_options is not None:
                enabled, opacity = self._pending_options
                self._pending_options = None
                self.set_options(enabled=enabled, opacity=opacity)
                return
            pending, self._pending_operation = self._pending_operation, None
            self._operation = None
            self.completed.emit(result)
            if isValid(self) and version == self._version:
                if pending is not None:
                    self._submit(*pending)
                else:
                    self.busy_changed.emit(False)

        try:
            handle = self._runner.submit(name, work, on_complete=complete)
            if self._busy and version == self._version:
                self._handle = handle
        except RuntimeError:
            complete(Result.failure(InfrastructureError("background_load_failed", "background_load_failed")))
        return True

    def dispose(self):
        self._disposed = True
        self._busy = False
        self._version += 1
        if self._handle is not None:
            self._handle.cancel()
        self._handle = None
        self._pending_options = self._pending_operation = self._prepared_background = None
