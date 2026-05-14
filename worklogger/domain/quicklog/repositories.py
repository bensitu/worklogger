"""Quick log repository Protocols."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from worklogger.domain.quicklog.models import QuickLog


class QuickLogRepository(Protocol):
    def add(self, quick_log: QuickLog) -> QuickLog:
        ...

    def update(self, quick_log: QuickLog) -> None:
        ...

    def remove(self, user_id: int, quick_log_id: int) -> None:
        ...

    def list_for_day(self, user_id: int, day: date) -> tuple[QuickLog, ...]:
        ...

    def list_for_range(
        self,
        user_id: int,
        start_day: date,
        end_day: date,
    ) -> tuple[QuickLog, ...]:
        ...

