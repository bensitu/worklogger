"""Reporting domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class ReportSource:
    kind: str
    identifier: str
    revision: int | None
    digest: str


@dataclass(frozen=True)
class ReportProvenance:
    generated_at: str = ""
    language: str = ""
    standard_hours: float = 8.0
    template_digest: str = ""
    sources: tuple[ReportSource, ...] = ()


@dataclass(frozen=True)
class Report:
    id: int | None
    user_id: int
    report_type: str
    period_start: date
    period_end: date
    content: str
    created_at: datetime | None = None
    revision: int = 0
    updated_at: datetime | None = None
    provenance: ReportProvenance = ReportProvenance()


@dataclass(frozen=True)
class ReportRevision:
    revision: int
    content: str
    saved_at: datetime | None
    provenance: ReportProvenance = ReportProvenance()

