"""Reporting domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class Report:
    id: int | None
    user_id: int
    report_type: str
    period_start: date
    period_end: date
    content: str
    created_at: datetime | None = None

