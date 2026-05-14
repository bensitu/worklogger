"""Work log repository Protocols."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from worklogger.domain.worklog.models import WorkLog


class WorkLogRepository(Protocol):
    def get_for_day(self, user_id: int, day: date) -> WorkLog | None:
        ...

    def list_for_month(self, user_id: int, year: int, month: int) -> tuple[WorkLog, ...]:
        ...

    def list_all(self, user_id: int) -> tuple[WorkLog, ...]:
        ...

    def save(self, work_log: WorkLog) -> None:
        ...

    def remove(self, user_id: int, day: date) -> None:
        ...

