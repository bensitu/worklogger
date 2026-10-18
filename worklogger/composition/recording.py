"""Desktop recording dependency composition."""

from __future__ import annotations

from tzlocal import get_localzone

from worklogger.app.use_cases.projects import ProjectService
from worklogger.app.use_cases.time_entries import TimeEntryService
from worklogger.app.use_cases.entry_types import EntryTypeService
from worklogger.app.use_cases.work_modes import WorkModeService
from worklogger.composition.context import RuntimeHandlers, RuntimeRepositories
from worklogger.domain.auth.models import User
from worklogger.infrastructure.i18n import get_language
from worklogger.presentation.viewmodels.time_entries import TimeEntryViewModel


def build_time_entry_view_model(
    user: User, repositories: RuntimeRepositories, handlers: RuntimeHandlers
) -> TimeEntryViewModel:
    return TimeEntryViewModel(
        TimeEntryService(
            user_id=user.id,
            repository=repositories.work_logs,
            settings=repositories.settings,
            local_timezone=get_localzone(),
            calendar_events=repositories.calendar_events,
            entry_types=EntryTypeService(user.id, repositories.entry_types),
            work_modes=WorkModeService(user.id, repositories.work_modes),
            projects=ProjectService(user.id, repositories.projects),
        ),
        rewrite_handler=handlers.rewrite_handler,
        language=get_language(),
    )
