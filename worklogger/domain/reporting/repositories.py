"""Report repository Protocols."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from worklogger.domain.reporting.models import Report
from worklogger.domain.reporting.templates import ReportTemplate


class ReportRepository(Protocol):
    def list_revisions(self, user_id: int, report_id: int): ...
    def list_revision_headers(self, user_id: int, report_id: int): ...
    def get_revision(self, user_id: int, report_id: int, revision: int): ...
    def restore_revision(self, user_id: int, report_id: int, revision: int, expected_revision: int) -> Report: ...

    def save(self, report: Report) -> Report:
        """Insert a new report or update the matching owned report by ID."""
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

    def remove(self, user_id: int, report_id: int, *, expected_content: str | None = None, expected_revision: int | None = None) -> None:
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
