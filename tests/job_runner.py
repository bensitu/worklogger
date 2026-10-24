"""Deterministic background execution for isolated application tests."""

from worklogger.app.job_runner import CancellationToken, JobCallable, JobCallback, JobHandle
from worklogger.presentation.job_runner import _run_job


class ImmediateJobRunner:
    def submit(self, name: str, job: JobCallable[object], *,
               on_complete: JobCallback[object] | None = None) -> JobHandle[object]:
        token = CancellationToken()
        result = _run_job(job, token)
        if on_complete is not None:
            on_complete(result)
        return JobHandle(job_id=f"{name}-immediate", cancel=token.cancel)
