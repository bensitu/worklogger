"""Report command DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from worklogger.domain.reporting.models import ReportProvenance


@dataclass(frozen=True)
class SaveReportCommand:
    user_id: int
    report_type: str
    period_start: date
    period_end: date
    content: str
    report_id: int | None = None
    revision: int = 0
    provenance: ReportProvenance = ReportProvenance()


@dataclass(frozen=True)
class GenerateReportCommand:
    user_id: int
    report_type: str
    period_start: date
    period_end: date
    language: str = "en_US"
    standard_work_hours: float = 8.0


@dataclass(frozen=True)
class DeleteReportCommand:
    user_id: int
    report_id: int
    expected_content: str | None = None


@dataclass(frozen=True)
class SaveReportTemplateCommand:
    user_id: int
    language: str
    template_type: str
    content: str


@dataclass(frozen=True)
class ResetReportTemplateCommand:
    user_id: int
    language: str
    template_type: str
