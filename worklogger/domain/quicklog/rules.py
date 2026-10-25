"""Historical quick log references and note deduplication."""

from __future__ import annotations

from worklogger.domain.quicklog.models import QuickLog
from worklogger.domain.notes.models import DailyNote
from collections.abc import Iterable
from worklogger.domain.shared.dates import time_range_label


def quick_log_reference(entry: QuickLog) -> str:
    span = time_range_label(entry.start_time, entry.end_time)
    return "- " + (span + " " if span else "") + entry.description


def contains_quick_log_reference(content: str, entry: QuickLog) -> bool:
    text = content.replace("\r\n", "\n").replace("\r", "\n")
    reference = quick_log_reference(entry).replace("\r\n", "\n").replace("\r", "\n")
    return "\n" + reference + "\n" in "\n" + text + "\n"


def unreferenced_quick_logs(entries: Iterable[QuickLog], notes: Iterable[DailyNote]) -> tuple[QuickLog, ...]:
    notes_by_day = {}
    for note in notes:
        notes_by_day.setdefault(note.day, []).append(note.content)
    return tuple(entry for entry in entries if not any(
        contains_quick_log_reference(content, entry) for content in notes_by_day.get(entry.day, ())))
