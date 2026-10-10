"""Bounded account-owned project summaries for any selected date range."""

import math
from worklogger.domain.analytics.projects import context_summaries
from worklogger.domain.shared.errors import InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.search import EntryFilter


class ProjectAnalyticsHandler:
    def __init__(self, repository, settings):
        self._repository, self._settings = repository, settings

    def handle(self, user_id, start, end):
        try:
            EntryFilter(start, end)
            entries = self._repository.list_entries_range(user_id, start, end, limit=50001)
            if len(entries) > 50000:
                raise ValueError("record_range_too_large")
            from worklogger.config.constants import STANDARD_WORK_HOURS_SETTING_KEY
            try:
                hours = float(self._settings.get(user_id, STANDARD_WORK_HOURS_SETTING_KEY, "8"))
                if not math.isfinite(hours):
                    raise ValueError()
                hours = max(1, min(hours, 24))
            except (TypeError, ValueError):
                hours = 8
            return Result.success(context_summaries(entries, hours))
        except ValueError as error:
            return Result.failure(ValidationError(str(error), str(error)))
        except Exception:
            return Result.failure(InfrastructureError("analytics_load_failed", "analytics_load_failed"))
