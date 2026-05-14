"""Report repository Protocols."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from worklogger.domain.reporting.models import Report
from worklogger.domain.reporting.templates import ReportTemplate


class ReportRepository(Protocol):
    def save(self, report: Report) -> Report:
        ...

    def get_for_period(
        self,
        user_id: int,
        report_type: str,
        period_start: date,
        period_end: date,
    ) -> Report | None:
        ...

    def list_by_type(self, user_id: int, report_type: str) -> tuple[Report, ...]:
        ...

    def remove(self, user_id: int, report_id: int) -> None:
        ...


class ReportTemplateRepository(Protocol):
    def save(self, template: ReportTemplate) -> ReportTemplate:
        ...

    def get(
        self,
        user_id: int,
        language: str,
        template_type: str,
    ) -> ReportTemplate | None:
        ...

    def list_for_user(
        self,
        user_id: int,
        language: str | None = None,
    ) -> tuple[ReportTemplate, ...]:
        ...

    def remove(self, user_id: int, language: str, template_type: str) -> None:
        ...
