"""Report query DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class GetReportForPeriodQuery:
    user_id: int
    report_type: str
    period_start: date
    period_end: date


@dataclass(frozen=True)
class ListReportsQuery:
    user_id: int
    report_type: str


@dataclass(frozen=True)
class GetReportTemplateQuery:
    user_id: int
    language: str
    template_type: str


@dataclass(frozen=True)
class ListReportTemplatesQuery:
    user_id: int
    language: str | None = None
