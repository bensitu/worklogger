"""Historical quick log references and note deduplication."""

from __future__ import annotations

from worklogger.domain.quicklog.models import QuickLog
from worklogger.domain.shared.dates import time_range_label


def quick_log_reference(entry: QuickLog) -> str:
    span = time_range_label(entry.start_time, entry.end_time)
    return "- " + (span + " " if span else "") + entry.description


def contains_quick_log_reference(content: str, entry: QuickLog) -> bool:
    text = content.replace("\r\n", "\n").replace("\r", "\n")
    reference = quick_log_reference(entry).replace("\r\n", "\n").replace("\r", "\n")
    return "\n" + reference + "\n" in "\n" + text + "\n"
