"""Notes repository Protocols."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from worklogger.domain.notes.models import DailyNote
from worklogger.domain.notes.preferences import NoteSharing
from worklogger.domain.quicklog.models import QuickLog


class DailyNoteRepository(Protocol):
    def get_for_day(self, user_id: int, day: date) -> DailyNote:
        ...

    def save(self, note: DailyNote, *, expected_content: str | None = None,
             sharing: NoteSharing | None = None, clear_draft: bool = False,
             expected_sharing: NoteSharing | None = None,
             previous_entries_to_remove: tuple[QuickLog, ...] = ()) -> None:
        ...

    def list_range(self, user_id: int, start: date, end: date) -> tuple[DailyNote, ...]:
        ...

    def search(self, user_id: int, query: str, *, limit: int = 50) -> tuple[DailyNote, ...]:
        ...
