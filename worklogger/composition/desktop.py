"""Account-scoped desktop session and window dependency assembly."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtWidgets import QApplication

from worklogger.app.job_runner import JobRunner
from worklogger.app.use_cases.work_planning import WorkPlanningService
from worklogger.app.use_cases.getting_started import GettingStartedService
from worklogger.app.use_cases.auth import (
    RevokeRememberedSessionHandler,
)
from worklogger.app.use_cases.backgrounds import BackgroundService
from worklogger.app.use_cases.calendar import (
    GetCalendarEventsForRangeHandler,
    GetHolidaysForRangeHandler,
)
from worklogger.app.use_cases.notes import GetDailyNoteHandler
from worklogger.composition.context import (
    RuntimeAuthRepository,
    RuntimeHandlers,
    RuntimeRepositories,
    build_runtime_handlers,
    build_runtime_repositories,
)
from worklogger.composition.recording import build_time_entry_view_model
from worklogger.composition.reporting import (
    build_analytics_workflow,
    build_notes_workflow,
    build_reports_workflow,
)
from worklogger.composition.settings import build_settings_workflow
from worklogger.config.constants import (
    LANGUAGE_SETTING_KEY,
    MINIMAL_MODE_SETTING_KEY,
)
from worklogger.domain.auth.models import User
from worklogger.domain.settings.values import setting_bool
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.database import (
    SQLiteConnectionFactory,
)
from worklogger.infrastructure.i18n import _, get_language, set_language
from worklogger.infrastructure.images.background import QtBackgroundImageLoader
from worklogger.infrastructure.language_preferences import (
    LanguagePreferences,
)
from worklogger.infrastructure.repositories import (
    SQLiteSettingsRepository,
)
from worklogger.presentation.auth import AuthSession
from worklogger.presentation.shell.getting_started import GettingStartedController
from worklogger.presentation.auth.controller import RememberSessionStore
from worklogger.presentation.notes import NotesWorkflowController
from worklogger.presentation.settings import SettingsWorkflowController
from worklogger.presentation.shell import (
    AppWindow,
    AppWindowConfig,
    MinimalView,
    MinimalViewConfig,
    QtResidencyController,
    ResidencyViewModel,
)
from worklogger.presentation.viewmodels import (
    AuthViewModel,
    CalendarViewModel,
    SettingsViewModel,
    StatsPanelViewModel,
)
from worklogger.presentation.viewmodels.time_entries import TimeEntryViewModel


@dataclass(frozen=True)
class DesktopRuntimeConfig:
    database_path: Path | str | None = None
    user_id: int | None = None
    create_user_if_empty: bool = False
    skip_remembered_session: bool = False
    bootstrap_username: str = "local"
    minimal_mode: bool | None = None
    password_iterations: int | None = None
    window: AppWindowConfig = AppWindowConfig()


@dataclass(frozen=True)
class DesktopRuntime:
    application: QApplication
    window: AppWindow | MinimalView
    connection_factory: SQLiteConnectionFactory
    user: User
    database_path: Path
    remember_session_store: RememberSessionStore
    job_runner: JobRunner | None = None
    auth_session: AuthSession | None = None
    local_inference: object | None = None
    revoke_remembered_session: Callable[[], Result[None]] | None = None


def build_user_runtime(
    *,
    application: QApplication,
    connection_factory: SQLiteConnectionFactory,
    database_path: Path,
    user: User,
    config: DesktopRuntimeConfig,
    auth_repository: RuntimeAuthRepository | None = None,
    auth_session: AuthSession | None = None,
    auth_view_model: AuthViewModel | None = None,
    remember_session_store: RememberSessionStore,
    language_preferences: LanguagePreferences,
    holiday_country: str,
    job_runner: JobRunner | None = None,
) -> Result[DesktopRuntime]:
    repositories = build_runtime_repositories(connection_factory)
    handlers = build_runtime_handlers(repositories, holiday_country=holiday_country, user_id=user.id,
                                 database_path=database_path, user_profiles=auth_repository)
    remember_store = remember_session_store
    settings_workflow = build_settings_workflow(
        user=user,
        database_path=database_path,
        connection_factory=connection_factory,
        repositories=repositories,
        handlers=handlers,
        auth_repository=auth_repository,
        auth_view_model=auth_view_model,
        remember_session_store=remember_store,
        job_runner=job_runner,
        save_login_language=language_preferences.save,
    )
    residency_controller = _build_residency_controller(user, handlers)
    window_config = _window_config_for_user(config.window, user)
    settings = SettingsViewModel(
        user_id=user.id,
        get_handler=handlers.settings_get_handler,
        set_handler=handlers.settings_set_handler,
        default_language=get_language(),
    ).load()
    if not settings.ok or settings.value is None:
        return Result.failure(
            settings.error
            or InfrastructureError("settings_load_failed", "settings_load_failed")
        )
    state = settings.value
    set_language(state.language)
    time_entry_view_model = build_time_entry_view_model(user, repositories, handlers)
    preferences = language_preferences
    if preferences.load() is None and repositories.settings.get(
        user.id, LANGUAGE_SETTING_KEY
    ):
        preferences.save(state.language)
    time_entry_view_model.set_default_break_hours(state.default_break_hours)
    time_entry_view_model.set_timer_reminders(state.timer_reminder_hours, state.continuous_timer_reminder_hours)
    window_config = replace(
        window_config,
        theme=state.theme,
        dark=state.dark_mode,
        custom_color=state.custom_color,
        standard_work_hours=state.standard_work_hours,
        monthly_target_hours=state.monthly_target_hours,
        profile_avatar_png=state.profile_avatar_png,
        show_recent_context=state.show_recent_context,
        calendar_options=replace(
            window_config.calendar_options,
            show_holidays=state.show_holidays,
            holiday_region=state.holiday_region,
            show_note_markers=state.show_note_markers,
            show_overnight_indicator=state.show_overnight_indicator,
            week_start_monday=state.week_start_monday,
        ),
    )

    if _minimal_mode_enabled(connection_factory, user, config):
        return _runtime_result(
            application=application,
            window=_build_minimal_view(
                time_entry_view_model=time_entry_view_model,
                notes_workflow=build_notes_workflow(
                    user, repositories, handlers, job_runner
                ),
                window_config=window_config,
                background_service=BackgroundService(user.id, repositories.background_images, QtBackgroundImageLoader()),
                holidays_handler=GetHolidaysForRangeHandler(handlers.holiday_provider),
                holiday_country=handlers.holiday_country,
                settings_workflow=settings_workflow,
                residency_controller=residency_controller,
                job_runner=job_runner,
            ),
            connection_factory=connection_factory,
            database_path=database_path,
            user=user,
            remember_session_store=remember_store,
            auth_session=auth_session,
            local_inference=handlers.local_inference,
            job_runner=job_runner,
            revoke_remembered_session=RevokeRememberedSessionHandler(auth_repository, user_id=user.id).handle,
        )

    return _runtime_result(
        application=application,
        window=_build_app_window(
            user=user,
            repositories=repositories,
            handlers=handlers,
            time_entry_view_model=time_entry_view_model,
            window_config=window_config,
            settings_workflow=settings_workflow,
            residency_controller=residency_controller,
            job_runner=job_runner,
        ),
        connection_factory=connection_factory,
        database_path=database_path,
        user=user,
        remember_session_store=remember_store,
        auth_session=auth_session,
        local_inference=handlers.local_inference,
        job_runner=job_runner,
        revoke_remembered_session=RevokeRememberedSessionHandler(auth_repository, user_id=user.id).handle,
    )


def _build_residency_controller(
    user: User,
    handlers: RuntimeHandlers,
) -> QtResidencyController:
    return QtResidencyController(
        ResidencyViewModel(
            user_id=user.id,
            get_handler=handlers.settings_get_handler,
            set_handler=handlers.settings_set_handler,
        )
    )


def _window_config_for_user(
    window_config: AppWindowConfig,
    user: User,
) -> AppWindowConfig:
    from worklogger.infrastructure.runtime_config import load_runtime_configuration

    features = load_runtime_configuration().features
    return replace(
        window_config,
        background_images_available=window_config.background_images_available and features.background_images,
        account_name=window_config.account_name or user.effective_display_name,
        account_role=_("Admin") if user.is_admin else _("User"),
    )


def _build_minimal_view(
    *,
    time_entry_view_model: TimeEntryViewModel,
    notes_workflow: NotesWorkflowController,
    window_config: AppWindowConfig,
    settings_workflow: SettingsWorkflowController | None,
    residency_controller: QtResidencyController,
    job_runner: JobRunner | None,
    background_service: BackgroundService,
    holidays_handler: GetHolidaysForRangeHandler,
    holiday_country: str,
) -> MinimalView:
    return MinimalView(
        time_entry_view_model=time_entry_view_model,
        config=MinimalViewConfig(
            selected_day=window_config.selected_day,
            today=window_config.today,
            account_name=window_config.account_name,
            theme=window_config.theme,
            dark=window_config.dark,
            custom_color=window_config.custom_color,
            background_images_available=window_config.background_images_available,
            show_recent_context=window_config.show_recent_context,
            week_start_monday=window_config.calendar_options.week_start_monday,
            show_holidays=window_config.calendar_options.show_holidays,
            holiday_region=window_config.calendar_options.holiday_region,
            confirm_discard_changes=window_config.confirm_discard_changes,
        ),
        settings_workflow=settings_workflow,
        notes_workflow=notes_workflow,
        residency_controller=residency_controller,
        job_runner=job_runner,
        background_service=background_service,
        holidays_handler=holidays_handler,
        holiday_country=holiday_country,
    )


def _build_app_window(
    *,
    user: User,
    repositories: RuntimeRepositories,
    handlers: RuntimeHandlers,
    time_entry_view_model: TimeEntryViewModel,
    window_config: AppWindowConfig,
    settings_workflow: SettingsWorkflowController | None,
    residency_controller: QtResidencyController,
    job_runner: JobRunner | None,
) -> AppWindow:
    return AppWindow(
        calendar_view_model=CalendarViewModel(
            user_id=user.id,
            month_records_handler=handlers.month_records_handler,
            calendar_events_handler=GetCalendarEventsForRangeHandler(
                repositories.calendar_events
            ),
            holidays_handler=GetHolidaysForRangeHandler(handlers.holiday_provider),
            holiday_country=handlers.holiday_country,
            notes_handler=GetDailyNoteHandler(repositories.daily_notes),
        ),
        time_entry_view_model=time_entry_view_model,
        stats_panel_view_model=StatsPanelViewModel(
            user_id=user.id,
            month_records_handler=handlers.month_records_handler,
            planning=WorkPlanningService(repositories.settings, handlers.holiday_provider, country=handlers.holiday_country),
        ),
        config=window_config,
        settings_workflow=settings_workflow,
        analytics_workflow=build_analytics_workflow(user, repositories, handlers),
        notes_workflow=build_notes_workflow(user, repositories, handlers, job_runner),
        reports_workflow=build_reports_workflow(user, repositories, handlers),
        residency_controller=residency_controller,
        job_runner=job_runner,
        background_service=BackgroundService(user.id, repositories.background_images, QtBackgroundImageLoader()),
    )


def _runtime_result(
    *,
    application: QApplication,
    window: AppWindow | MinimalView,
    connection_factory: SQLiteConnectionFactory,
    database_path: Path,
    user: User,
    remember_session_store: RememberSessionStore,
    auth_session: AuthSession | None,
    job_runner: JobRunner | None,
    local_inference=None,
    revoke_remembered_session=None,
) -> Result[DesktopRuntime]:
    settings_workflow = getattr(window, "_settings_workflow", None)
    window.getting_started = GettingStartedController(window,
        GettingStartedService(SQLiteSettingsRepository(connection_factory), user_id=user.id), job_runner=job_runner)
    if settings_workflow is not None:
        settings_workflow.set_restore_handler(window.logout_requested.emit)
        settings_workflow.start_cloud_backups(window)
        if isinstance(window, MinimalView):
            settings_workflow.initialize_processing(window, window.entry_panel.refresh_ai_availability)
        else:
            settings_workflow.initialize_processing(window, window.refresh_ai_availability)
    return Result.success(
        DesktopRuntime(
            application=application,
            window=window,
            connection_factory=connection_factory,
            user=user,
            database_path=database_path,
            remember_session_store=remember_session_store,
            job_runner=job_runner,
            auth_session=replace(auth_session, remember_token=None, recovery_key=None) if auth_session is not None else None,
            local_inference=local_inference,
            revoke_remembered_session=revoke_remembered_session,
        )
    )


def _minimal_mode_enabled(
    connection_factory: SQLiteConnectionFactory,
    user: User,
    config: DesktopRuntimeConfig,
) -> bool:
    from worklogger.infrastructure.runtime_config import load_runtime_configuration

    if not load_runtime_configuration().features.minimal_view:
        return False
    if config.minimal_mode is not None:
        return bool(config.minimal_mode)
    settings = SQLiteSettingsRepository(connection_factory)
    return setting_bool(settings.get(user.id, MINIMAL_MODE_SETTING_KEY))
