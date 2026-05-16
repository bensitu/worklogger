"""Qt-backed background job runner for presentation workflows."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from worklogger.app.job_runner import (
    CancellationToken,
    JobCallable,
    JobCallback,
    JobHandle,
)
from worklogger.domain.shared.errors import CancellationError, InfrastructureError
from worklogger.domain.shared.result import Result

LOGGER = logging.getLogger(__name__)


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
    """Run application jobs in Qt's global thread pool and report on the UI thread."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool.globalInstance()
        self._callbacks: dict[str, JobCallback[object] | None] = {}
        self._tokens: dict[str, CancellationToken] = {}
        self._signals = _JobSignals()
        self._signals.completed.connect(self._complete)

    def submit(
        self,
        name: str,
        job: JobCallable[object],
        *,
        on_complete: JobCallback[object] | None = None,
    ) -> JobHandle[object]:
        job_id = f"{name}-{uuid.uuid4().hex}"
        token = CancellationToken()
        self._tokens[job_id] = token
        self._callbacks[job_id] = on_complete
        self._pool.start(
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
                {"reason": str(exc)},
            )
        )
    if isinstance(value, Result):
        return value
    return Result.success(value)


class ImmediateJobRunner:
    """Synchronous JobRunner implementation for tests and non-interactive smoke checks."""

    def submit(
        self,
        name: str,
        job: JobCallable[object],
        *,
        on_complete: JobCallback[object] | None = None,
    ) -> JobHandle[object]:
        token = CancellationToken()
        result = _run_job(job, token)
        if on_complete is not None:
            on_complete(result)
        return JobHandle(job_id=f"{name}-immediate", cancel=token.cancel)
