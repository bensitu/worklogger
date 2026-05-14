"""Calendar repository Protocols."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from worklogger.domain.calendar.models import CalendarEvent, Holiday


class HolidayProvider(Protocol):
    def list_for_range(
        self,
        country: str,
        start_day: date,
        end_day: date,
    ) -> tuple[Holiday, ...]:
        ...


class CalendarEventRepository(Protocol):
    def list_for_day(self, user_id: int, day: date) -> tuple[CalendarEvent, ...]:
        ...

    def list_for_range(
        self,
        user_id: int,
        start_day: date,
        end_day: date,
    ) -> tuple[CalendarEvent, ...]:
        ...

    def replace_all(self, user_id: int, events: tuple[CalendarEvent, ...]) -> int:
        ...

    def add_many(self, user_id: int, events: tuple[CalendarEvent, ...]) -> int:
        ...

    def clear(self, user_id: int) -> None:
        ...
