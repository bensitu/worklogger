"""Background job contracts for application use cases."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Event
from typing import Generic, Protocol, TypeVar

from worklogger.domain.shared.result import Result

T = TypeVar("T")


class CancellationToken:
    """Cooperative cancellation flag for long-running jobs."""

    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()


@dataclass(frozen=True)
class JobHandle(Generic[T]):
    job_id: str
    cancel: Callable[[], None]


JobCallable = Callable[[CancellationToken], T]
JobCallback = Callable[[Result[T]], None]


class JobRunner(Protocol):
    """Port for running long operations outside the UI thread."""

    def submit(
        self,
        name: str,
        job: JobCallable[T],
        *,
        on_complete: JobCallback[T] | None = None,
    ) -> JobHandle[T]:
        ...

