"""Qt-backed background job runner for presentation workflows."""

from __future__ import annotations

import logging
import uuid
from time import monotonic
from weakref import ref

from PySide6.QtCore import QCoreApplication, QEventLoop, QObject, QRunnable, QThread, QThreadPool, Signal
from shiboken6 import isValid

from worklogger.app.job_runner import (
    CancellationToken,
    JobCallable,
    JobCallback,
    JobHandle,
)
from worklogger.domain.shared.errors import CancellationError, InfrastructureError
from worklogger.domain.shared.result import Result

LOGGER = logging.getLogger(__name__)


def shared_job_runner() -> QtJobRunner:
    application = QCoreApplication.instance()
    if application is None:
        raise RuntimeError("qt_application_required")
    runner = getattr(application, "_worklogger_job_runner", None)
    if runner is None or not isValid(runner) or runner._closed:
        runner = QtJobRunner(application)
        application._worklogger_job_runner = runner
    return runner


def owned_callback(owner: QObject, callback):
    reference = ref(owner)

    def completed(result):
        current = reference()
        if current is not None and isValid(current):
            callback(result)

    return completed


class _JobSignals(QObject):
    completed = Signal(str, object)


class _JobRunnable(QRunnable):
    def __init__(
        self,
        *,
        job_id: str,
        token: CancellationToken,
        job: JobCallable[object],
        signals: _JobSignals,
    ) -> None:
        super().__init__()
        self._job_id = job_id
        self._token = token
        self._job = job
        self._signals = signals

    def run(self) -> None:
        if self._token.is_cancelled():
            result = Result.failure(
                CancellationError("job_cancelled", "job_cancelled")
            )
        else:
            result = _run_job(self._job, self._token)
        self._signals.completed.emit(self._job_id, result)


class QtJobRunner(QObject):
    """Run application jobs in an owned thread pool and report on the UI thread."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(max(2, self._pool.maxThreadCount()))
        self._long_pool = QThreadPool(self)
        self._long_pool.setMaxThreadCount(2)
        self._render_pool = QThreadPool(self)
        self._render_pool.setMaxThreadCount(2)
        self._transfer_pool = QThreadPool(self)
        self._transfer_pool.setMaxThreadCount(2)
        self._pools = (self._pool, self._long_pool, self._render_pool, self._transfer_pool)
        self._closed = False
        self._callbacks: dict[str, JobCallback[object] | None] = {}
        self._tokens: dict[str, CancellationToken] = {}
        self._signals = _JobSignals()
        self._signals.completed.connect(self._complete)
        application = QCoreApplication.instance()
        if application is not None:
            application.aboutToQuit.connect(self.shutdown)

    def shutdown(self, *, wait: bool = False, timeout_ms: int = 5000) -> bool:
        self._closed = True
        for token in self._tokens.values():
            token.cancel()
        self._tokens.clear()
        self._callbacks.clear()
        for pool in self._pools:
            pool.clear()
        if wait:
            deadline = monotonic() + max(0, timeout_ms) / 1000
            application = QCoreApplication.instance()
            while True:
                if all(pool.waitForDone(0) for pool in self._pools):
                    return True
                if monotonic() >= deadline:
                    return False
                if application is not None and QThread.currentThread() == application.thread():
                    application.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents, 10)
                for pool in self._pools:
                    pool.waitForDone(10)
        return not any(pool.activeThreadCount() for pool in self._pools)

    def submit(
        self,
        name: str,
        job: JobCallable[object],
        *,
        on_complete: JobCallback[object] | None = None,
    ) -> JobHandle[object]:
        if self._closed:
            raise RuntimeError("job_runner_closed")
        job_id = f"{name}-{uuid.uuid4().hex}"
        token = CancellationToken()
        self._tokens[job_id] = token
        self._callbacks[job_id] = on_complete
        long_running = name.startswith(("ai_", "local_model_")) or name in {
            "cloud_backup", "generate_report", "check_updates", "identity_authorization", "initialize_text_processing",
        }
        if name == "glass_background":
            pool = self._render_pool
        elif name.startswith("local_model_") or name == "identity_authorization":
            pool = self._transfer_pool
        else:
            pool = self._long_pool if long_running else self._pool
        pool.start(
            _JobRunnable(
                job_id=job_id,
                token=token,
                job=job,
                signals=self._signals,
            )
        )
        return JobHandle(job_id=job_id, cancel=token.cancel)

    def _complete(self, job_id: str, result: object) -> None:
        self._tokens.pop(job_id, None)
        callback = self._callbacks.pop(job_id, None)
        if callback is None:
            return
        try:
            callback(result)
        except Exception:
            LOGGER.exception("background_job_callback_failed", extra={"job_id": job_id})


def _run_job(job: JobCallable[object], token: CancellationToken) -> Result[object]:
    try:
        value = job(token)
    except Exception as exc:
        LOGGER.exception("background_job_failed")
        return Result.failure(
            InfrastructureError(
                "background_job_failed",
                "background_job_failed",
                {"reason": type(exc).__name__},
            )
        )
    if isinstance(value, Result):
        return value
    return Result.success(value)
