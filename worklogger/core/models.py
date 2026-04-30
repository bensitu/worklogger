"""Shared domain models — typed wrappers around raw DB rows.

Using NamedTuple means ``WorkRecord(*row)`` is a zero-cost, always-safe
way to turn a raw SQLite tuple into a fully typed record. All code that
previously used ``rec[1]``, ``rec[5]``, ``len(rec) > 5`` etc. can now
use plain attribute access.
"""

from __future__ import annotations
from typing import NamedTuple


class WorkRecord(NamedTuple):
    """One row from the ``worklog`` table.

    Field order matches the CREATE TABLE definition exactly so
    ``WorkRecord(*sqlite_row)`` is always correct.

    Columns
    -------
    date        – "YYYY-MM-DD" primary key
    start       – "HH:MM" or None / ""
    end         – "HH:MM" or None / ""
    break_hours – float hours or None
    note        – free-text or None / ""
    work_type   – one of WORK_TYPE_KEYS; defaults to "normal"
    overnight   – 1 when end time is on the next day, else 0
    """

    date: str
    start: str | None
    end: str | None
    break_hours: float | None
    note: str | None
    work_type: str = "normal"
    overnight: int = 0

    # Computed helpers (pure, no side effects).

    @property
    def has_times(self) -> bool:
        """True when both start and end are present."""
        return bool(self.start and self.end)

    @property
    def is_leave(self) -> bool:
        """True when work_type is one of the leave categories."""
        from config.constants import LEAVE_TYPES
        return self.safe_work_type() in LEAVE_TYPES

    def safe_work_type(self) -> str:
        """Return work_type, falling back to 'normal' for NULL / empty rows."""
        return self.work_type or "normal"

    def safe_note(self) -> str:
        """Return note string, never None."""
        return self.note or ""

    @property
    def is_overnight(self) -> bool:
        return bool(self.overnight)
