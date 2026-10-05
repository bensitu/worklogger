"""Notes repository Protocols."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from worklogger.domain.notes.models import DailyNote


class DailyNoteRepository(Protocol):
    def get_for_day(self, user_id: int, day: date) -> DailyNote:
        ...

    def save(self, note: DailyNote, *, expected_content: str | None = None) -> None:
        ...

    def list_range(self, user_id: int, start: date, end: date) -> tuple[DailyNote, ...]:
        ...
