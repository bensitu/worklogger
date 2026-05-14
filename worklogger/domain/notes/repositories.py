"""Notes repository Protocols."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from worklogger.domain.notes.models import DailyNote


class DailyNoteRepository(Protocol):
    def get_for_day(self, user_id: int, day: date) -> DailyNote:
        ...

    def save(self, note: DailyNote) -> None:
        ...
