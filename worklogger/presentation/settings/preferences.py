"""Ordered preference writes and coalesced settings refresh."""

from collections import deque

from PySide6.QtCore import QObject, QTimer

from worklogger.app.failures import infrastructure_failure, storage_boundary
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import _
from worklogger.presentation.job_runner import owned_callback


class PreferenceSaveController(QObject):
    def __init__(self, parent, *, load_state, on_state, on_error, on_saved, on_busy, on_refresh_busy):
        super().__init__(parent)
        self._load_state = load_state
        self._on_state = on_state
        self._on_error = on_error
        self._on_saved = on_saved
        self._on_busy = on_busy
        self._on_refresh_busy = on_refresh_busy
        self._runner = None
        self._queue = deque()
        self._active = False
        self._refreshing = False
        self._refresh_version = 0
        self._refresh_handle = None
        self._pending_refresh = None
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._reload_state)
        parent.destroyed.connect(self.dispose)

    def set_job_runner(self, runner):
        if runner is not self._runner:
            self.cancel_refresh()
        self._runner = runner

    def cancel_refresh(self):
        self._refresh_timer.stop()
        self._refresh_version += 1
        if self._refresh_handle is not None:
            self._refresh_handle.cancel()
        self._refresh_handle = None
        self._pending_refresh = None
        if self._refreshing:
            self._refreshing = False
            self._on_refresh_busy(False)

    def dispose(self):
        self._refresh_version += 1
        if self._refresh_handle is not None:
            self._refresh_handle.cancel()
        self._refresh_handle = None
        self._pending_refresh = None
        self._refresh_timer.stop()

    def refresh(self, load_state, on_state):
        if self._refreshing or self._pending_refresh is not None:
            return True
        self._refresh_timer.stop()
        if self._active or self._queue:
            self._pending_refresh = (load_state, on_state)
            return True
        if self._runner is None:
            return self._display_state(self._read_state(load_state), on_state)
        self._refresh_version += 1
        version = self._refresh_version
        self._refreshing = True
        self._on_refresh_busy(True)
        completed = False

        def complete(result):
            nonlocal completed
            if completed or version != self._refresh_version:
                return
            completed = True
            self._refresh_handle = None
            try:
                self._display_state(result, on_state)
            finally:
                if version == self._refresh_version:
                    self._refreshing = False
                    self._on_refresh_busy(False)

        try:
            handle = self._runner.submit("load_settings", lambda _token: self._read_state(load_state),
                on_complete=owned_callback(self, complete))
            if not completed and version == self._refresh_version:
                self._refresh_handle = handle
        except Exception as error:
            complete(Result.failure(infrastructure_failure("settings_load_failed", error, logger_name=__name__)))
            return False
        return True

    def _display_state(self, result, on_state):
        if not result.ok or result.value is None:
            self._on_error(result.error)
            return False
        try:
            on_state(result.value)
        except Exception as error:
            self._on_error(infrastructure_failure("settings_load_failed", error, logger_name=__name__))
            return False
        return True

    def save(self, operation, *, message=None):
        self.cancel_refresh()
        if self._runner is None:
            result = _execute(operation)
            if not result.ok:
                self._on_error(result.error)
                return
            self._refresh_timer.start(0)
            self._on_saved(message or _("Saved"))
            return
        self._queue.append((operation, message))
        self._save_next()

    def _save_next(self):
        if self._active:
            return
        if not self._queue:
            self._on_busy(False)
            if self._pending_refresh is not None:
                load_state, on_state = self._pending_refresh
                self._pending_refresh = None
                self.refresh(load_state, on_state)
            return
        operation, message = self._queue.popleft()
        self._refresh_timer.stop()
        self._active = True
        self._on_busy(True)

        def work(_token):
            result = _execute(operation)
            return self._read_state() if result.ok else result

        completed = False

        def complete(result):
            nonlocal completed
            if completed:
                return
            completed = True
            try:
                if result.ok and result.value is not None:
                    if not self._queue:
                        self._on_state(result.value)
                    self._on_saved(message or _("Saved"))
                else:
                    self._on_error(result.error)
            except Exception as error:
                self._on_error(infrastructure_failure("settings_load_failed", error, logger_name=__name__))
            finally:
                self._active = False
                self._save_next()

        try:
            self._runner.submit("save_preferences", work, on_complete=owned_callback(self, complete))
        except Exception as error:
            if not completed:
                complete(Result.failure(infrastructure_failure("settings_save_failed", error, logger_name=__name__)))

    def _reload_state(self):
        self.refresh(self._load_state, self._on_state)

    @storage_boundary("settings_load_failed")
    def _read_state(self, load_state=None):
        return (load_state or self._load_state)()


@storage_boundary("settings_save_failed")
def _execute(operation):
    return operation()
