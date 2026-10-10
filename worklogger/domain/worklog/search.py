"""Bounded individual-record queries and stable chronological paging."""

from dataclasses import dataclass
from datetime import date
from worklogger.domain.projects.models import validate_identifier
from worklogger.domain.worklog.models import WorkLog


@dataclass(frozen=True)
class EntryFilter:
    start: date
    end: date
    text: str = ""
    work_type: str | None = None
    project_id: str | None = None
    work_item_id: str | None = None
    unclassified: bool = False

    def __post_init__(self):
        if (type(self.start) is not date or type(self.end) is not date or self.end < self.start
                or not isinstance(self.text, str) or len(self.text) > 512
                or any(ord(char) < 32 for char in self.text)):
            raise ValueError("record_search_invalid")
        if self.work_type is not None and (not isinstance(self.work_type, str) or len(self.work_type) > 80):
            raise ValueError("record_search_invalid")
        for identifier in (self.project_id, self.work_item_id):
            if identifier is not None:
                validate_identifier(identifier)


@dataclass(frozen=True)
class EntryCursor:
    day: str
    start: str
    entry_id: int

    def __post_init__(self):
        date.fromisoformat(self.day)
        if not isinstance(self.start, str) or len(self.start) > 16 or type(self.entry_id) is not int or self.entry_id < 1:
            raise ValueError("record_search_invalid")


@dataclass(frozen=True)
class EntryPage:
    entries: tuple[WorkLog, ...]
    next_cursor: EntryCursor | None = None
