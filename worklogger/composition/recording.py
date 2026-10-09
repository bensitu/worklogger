"""Desktop recording dependency composition."""

from __future__ import annotations

from tzlocal import get_localzone

from worklogger.app.use_cases.time_entries import TimeEntryService
from worklogger.app.use_cases.work_types import WorkTypeService
from worklogger.composition.context import RuntimeHandlers, RuntimeRepositories
from worklogger.domain.auth.models import User
from worklogger.infrastructure.i18n import get_language
from worklogger.presentation.viewmodels.time_entries import TimeEntryViewModel


def _build_time_entry_view_model(
    user: User, repositories: RuntimeRepositories, handlers: RuntimeHandlers
) -> TimeEntryViewModel:
    return TimeEntryViewModel(
        TimeEntryService(
            user_id=user.id,
            repository=repositories.work_logs,
            settings=repositories.settings,
            local_timezone=get_localzone(),
            calendar_events=repositories.calendar_events,
            work_types=WorkTypeService(user.id, repositories.work_types),
        ),
        rewrite_handler=handlers.rewrite_handler,
        language=get_language(),
    )
