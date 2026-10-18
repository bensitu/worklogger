"""Paged report summaries and owned report selection."""

from worklogger.app.use_cases._errors import storage_boundary
from worklogger.domain.reporting.history import ReportHistoryFilter
from worklogger.domain.reporting.repositories import ReportRepository
from worklogger.domain.shared.errors import NotFoundError, ValidationError
from worklogger.domain.shared.result import Result


class ReportHistoryService:
    def __init__(self, user_id: int, repository: ReportRepository, *, page_size: int = 50):
        self._user_id, self._repository = user_id, repository
        self._page_size = page_size

    @storage_boundary("report_history_failed")
    def browse(self, criteria, *, cursor=None):
        if not isinstance(criteria, ReportHistoryFilter):
            return Result.failure(ValidationError("report_history_filter_invalid", "report_history_filter_invalid"))
        return Result.success(self._repository.search_history(self._user_id, criteria, cursor=cursor, limit=self._page_size))

    @storage_boundary("report_load_failed")
    def get(self, report_id):
        if type(report_id) is not int or report_id < 1:
            return Result.failure(ValidationError("report_not_found", "report_not_found"))
        report = self._repository.get_by_id(self._user_id, report_id)
        if report is None:
            return Result.failure(NotFoundError("report_not_found", "report_not_found"))
        return Result.success(report)
