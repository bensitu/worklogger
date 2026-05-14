"""Quick log validation and normalization."""

from __future__ import annotations

from dataclasses import replace

from worklogger.domain.quicklog.models import QuickLog
from worklogger.domain.worklog.rules import parse_minutes, parse_time


def normalize_description(description: str) -> str:
    if not isinstance(description, str):
        raise TypeError("description_must_be_string")
    cleaned = description.strip()
    if not cleaned:
        raise ValueError("description_required")
    return cleaned


def normalize_quick_log(quick_log: QuickLog) -> QuickLog:
    description = normalize_description(quick_log.description)
    start_time = parse_time(quick_log.start_time) or ""
    end_time = parse_time(quick_log.end_time) or ""
    if end_time and not start_time:
        raise ValueError("start_time_required")
    if start_time and end_time:
        start_minutes = parse_minutes(start_time)
        end_minutes = parse_minutes(end_time)
        if start_minutes is None or end_minutes is None or end_minutes <= start_minutes:
            raise ValueError("quick_log_time_range_invalid")
    return replace(
        quick_log,
        description=description,
        start_time=start_time,
        end_time=end_time,
    )
