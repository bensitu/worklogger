"""Notes domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

MAX_NOTE_CONTENT_BYTES = 1024 * 1024


@dataclass(frozen=True)
class DailyNote:
    user_id: int
    day: date
    content: str = ""


@dataclass(frozen=True)
class NoteHistoryFilter:
    start: date = date.min
    end: date = date.max
    text: str = ""
    before: date | None = None
    limit: int = 50

    def __post_init__(self):
        if (not isinstance(self.start, date) or not isinstance(self.end, date)
                or self.start > self.end or type(self.limit) is not int or not 1 <= self.limit <= 100):
            raise ValueError("note_load_failed")


@dataclass(frozen=True)
class NotePreview:
    day: date
    text: str


@dataclass(frozen=True)
class NoteHistoryPage:
    notes: tuple[NotePreview, ...]
    total: int
    next_before: date | None = None
