"""Report use cases."""

from __future__ import annotations

from worklogger.app.commands.report_commands import (
    DeleteReportCommand,
    ResetReportTemplateCommand,
    SaveReportCommand,
    SaveReportTemplateCommand,
)
from worklogger.app.ports import TemplateProvider as TemplateProvider
from worklogger.app.queries.report_queries import (
    GetReportForPeriodQuery,
    GetReportTemplateQuery,
    ListReportsQuery,
    ListReportTemplatesQuery,
)
from worklogger.app.use_cases._errors import storage_boundary
from worklogger.app.use_cases.report_generation import GeneratedReport as GeneratedReport
from worklogger.app.use_cases.report_generation import GenerateReportHandler as GenerateReportHandler
from worklogger.domain.reporting.models import Report
from worklogger.domain.reporting.periods import normalize_report_type, validate_report_period
from worklogger.domain.reporting.repositories import ReportRepository, ReportTemplateRepository
from worklogger.domain.reporting.templates import (
    ReportTemplate,
    normalize_template_language,
    normalize_template_type,
)
from worklogger.domain.shared.errors import ConflictError, InfrastructureError, NotFoundError, ValidationError
from worklogger.domain.shared.result import Result


class SaveReportHandler:
    def __init__(self, repository: ReportRepository) -> None:
        self._repository = repository

    def handle(self, command: SaveReportCommand) -> Result[Report]:
        try:
            period = validate_report_period(
                command.report_type,
                command.period_start,
                command.period_end,
            )
            if not isinstance(command.content, str) or not command.content.strip():
                raise ValueError("report_content_required")
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        report = Report(
            id=command.report_id,
            user_id=command.user_id,
            report_type=period.report_type,
            period_start=period.start,
            period_end=period.end,
            content=command.content,
            revision=command.revision,
            provenance=command.provenance,
        )
        try:
            return Result.success(self._repository.save(report))
        except ValueError as exc:
            if str(exc) == "report_conflict":
                return Result.failure(ConflictError("report_conflict", "report_conflict"))
            if str(exc) == "report_not_found":
                return Result.failure(NotFoundError("report_not_found", "report_not_found"))
            return Result.failure(ValidationError(str(exc), str(exc)))
        except Exception:
            return Result.failure(InfrastructureError("report_save_failed", "report_save_failed"))


class DeleteReportHandler:
    def __init__(self, repository: ReportRepository) -> None:
        self._repository = repository

    def handle(self, command: DeleteReportCommand) -> Result[None]:
        try:
            if command.expected_revision is not None:
                self._repository.remove(command.user_id, command.report_id,
                    expected_content=command.expected_content, expected_revision=command.expected_revision)
            elif command.expected_content is None:
                self._repository.remove(command.user_id, command.report_id)
            else:
                self._repository.remove(command.user_id, command.report_id, expected_content=command.expected_content)
            return Result.success(None)
        except ValueError as exc:
            if str(exc) == "report_not_found":
                return Result.failure(NotFoundError("report_not_found", "report_not_found"))
            if str(exc) == "report_conflict":
                return Result.failure(ConflictError("report_conflict", "report_conflict"))
            return Result.failure(InfrastructureError("report_delete_failed", "report_delete_failed"))
        except Exception:
            return Result.failure(InfrastructureError("report_delete_failed", "report_delete_failed"))


class ReportRevisionService:
    def __init__(self, repository):
        self._repository = repository

    def list(self, user_id, report_id):
        return self._run(lambda: self._repository.list_revisions(user_id, report_id))

    def list_headers(self, user_id, report_id):
        return self._run(lambda: self._repository.list_revision_headers(user_id, report_id))

    def get(self, user_id, report_id, revision):
        return self._run(lambda: self._repository.get_revision(user_id, report_id, revision))

    def restore(self, user_id, report_id, revision, expected_revision):
        return self._run(lambda: self._repository.restore_revision(user_id, report_id, revision, expected_revision))

    @staticmethod
    def _run(operation):
        try:
            return Result.success(operation())
        except ValueError as error:
            if str(error) == "report_conflict":
                return Result.failure(ConflictError("report_conflict", "report_conflict"))
            if str(error) == "report_not_found":
                return Result.failure(NotFoundError("report_not_found", "report_not_found"))
            return Result.failure(InfrastructureError("report_history_failed", "report_history_failed"))
        except Exception:
            return Result.failure(InfrastructureError("report_history_failed", "report_history_failed"))


class GetReportForPeriodHandler:
    def __init__(self, repository: ReportRepository) -> None:
        self._repository = repository

    @storage_boundary("report_load_failed")
    def handle(self, query: GetReportForPeriodQuery) -> Result[Report | None]:
        try:
            period = validate_report_period(
                query.report_type,
                query.period_start,
                query.period_end,
            )
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        return Result.success(
            self._repository.get_for_period(
                query.user_id,
                period.report_type,
                period.start,
                period.end,
            )
        )


class ListReportsHandler:
    def __init__(self, repository: ReportRepository) -> None:
        self._repository = repository

    def handle(self, query: ListReportsQuery) -> Result[tuple[Report, ...]]:
        try:
            report_type = normalize_report_type(query.report_type)
            if (query.period_start is None) != (query.period_end is None):
                raise ValueError("report_period_invalid")
            if query.period_start is not None and query.period_end < query.period_start:
                raise ValueError("report_period_invalid")
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        try:
            if query.period_start is not None and query.period_end is not None:
                reader = getattr(self._repository, "list_range", None)
                if reader is not None:
                    return Result.success(reader(query.user_id, report_type, query.period_start, query.period_end))
                return Result.success(tuple(row for row in self._repository.list_by_type(query.user_id, report_type)
                                            if query.period_start <= row.period_start <= query.period_end))
            return Result.success(self._repository.list_by_type(query.user_id, report_type))
        except Exception:
            return Result.failure(InfrastructureError("report_history_failed", "report_history_failed"))


class SaveReportTemplateHandler:
    def __init__(self, repository: ReportTemplateRepository) -> None:
        self._repository = repository

    def handle(self, command: SaveReportTemplateCommand) -> Result[ReportTemplate]:
        try:
            template_type = normalize_template_type(command.template_type)
            language = normalize_template_language(command.language)
            if not isinstance(command.content, str) or not command.content.strip():
                raise ValueError("template_content_required")
            if len(command.content.encode("utf-8")) > 1024 * 1024:
                raise ValueError("template_content_too_long")
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        template = ReportTemplate(
            id=None,
            user_id=command.user_id,
            language=language,
            template_type=template_type,
            content=command.content,
        )
        try:
            return Result.success(self._repository.save(template))
        except Exception:
            return Result.failure(InfrastructureError("template_save_failed", "template_save_failed"))


class ResetReportTemplateHandler:
    def __init__(self, repository: ReportTemplateRepository) -> None:
        self._repository = repository

    def handle(self, command: ResetReportTemplateCommand) -> Result[None]:
        try:
            template_type = normalize_template_type(command.template_type)
            language = normalize_template_language(command.language)
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        try:
            self._repository.remove(command.user_id, language, template_type)
        except Exception:
            return Result.failure(InfrastructureError("template_save_failed", "template_save_failed"))
        return Result.success(None)


class GetReportTemplateHandler:
    def __init__(self, repository: ReportTemplateRepository) -> None:
        self._repository = repository

    def handle(self, query: GetReportTemplateQuery) -> Result[ReportTemplate | None]:
        try:
            template_type = normalize_template_type(query.template_type)
            language = normalize_template_language(query.language)
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        try:
            return Result.success(self._repository.get(query.user_id, language, template_type))
        except Exception:
            return Result.failure(InfrastructureError("template_load_failed", "template_load_failed"))


class ListReportTemplatesHandler:
    def __init__(self, repository: ReportTemplateRepository) -> None:
        self._repository = repository

    def handle(self, query: ListReportTemplatesQuery) -> Result[tuple[ReportTemplate, ...]]:
        try:
            language = normalize_template_language(query.language) if query.language is not None else None
            return Result.success(self._repository.list_for_user(query.user_id, language))
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        except Exception:
            return Result.failure(InfrastructureError("template_load_failed", "template_load_failed"))
