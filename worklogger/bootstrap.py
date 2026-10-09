"""Runtime composition root for desktop presentation."""

from __future__ import annotations

import logging
import secrets
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from PySide6.QtWidgets import QApplication

from worklogger.__about__ import APP_ID, APP_NAME, APP_VERSION
from worklogger.app.job_runner import JobRunner
from worklogger.app.use_cases.auth import (
    ChangePasswordHandler,
    GetAuthBootstrapStateHandler,
    LoginHandler,
    LoginWithRememberTokenHandler,
    RegisterUserHandler,
    ResetPasswordHandler,
)
from worklogger.app.use_cases.calendar import (
    GetCalendarEventsForRangeHandler,
    GetHolidaysForRangeHandler,
)
from worklogger.app.use_cases.notes import GetDailyNoteHandler
from worklogger.composition.context import (
    RuntimeAuthRepository,
    RuntimeHandlers,
    RuntimeRepositories,
    _runtime_handlers,
    _runtime_repositories,
)
from worklogger.composition.recording import _build_time_entry_view_model
from worklogger.composition.reporting import (
    _build_analytics_workflow,
    _build_notes_workflow,
    _build_reports_workflow,
)
from worklogger.composition.settings import _build_settings_workflow
from worklogger.config.constants import (
    LANGUAGE_SETTING_KEY,
    MINIMAL_MODE_SETTING_KEY,
)
from worklogger.domain.auth.models import User
from worklogger.domain.auth.repositories import AuthCredentialRepository
from worklogger.domain.shared.errors import InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.calendar import (
    detect_country,
)
from worklogger.infrastructure.database import (
    MigrationRunner,
    SQLiteConnectionFactory,
    default_database_path,
)
from worklogger.infrastructure.database.upgrade import copy_database
from worklogger.infrastructure.i18n import _, get_language, set_language
from worklogger.infrastructure.language_preferences import (
    LanguagePreferences,
    initialize_language,
)
from worklogger.infrastructure.logging import setup_logging
from worklogger.infrastructure.repositories import (
    SQLiteAuthRepository,
    SQLiteLoginFailureRepository,
    SQLiteSettingsRepository,
)
from worklogger.infrastructure.security import (
    FileRememberTokenSessionStore,
    PBKDF2PasswordHasher,
)
from worklogger.infrastructure.security.key_store import (
    HmacSecretBox,
    protect_legacy_proxy_passwords,
)
from worklogger.presentation.auth import AuthController, AuthSession
from worklogger.presentation.auth.controller import RememberSessionStore
from worklogger.presentation.job_runner import QtJobRunner
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
from worklogger.presentation.theme import (
    configure_application_style,
    install_bundled_fonts,
)
from worklogger.presentation.viewmodels import (
    AuthViewModel,
    CalendarViewModel,
    SettingsViewModel,
    StatsPanelViewModel,
)
from worklogger.presentation.viewmodels.time_entries import TimeEntryViewModel
from worklogger.presentation.widgets.assets import apply_application_icon

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class DesktopRuntimeConfig:
    database_path: Path | str | None = None
    user_id: int | None = None
    create_user_if_empty: bool = False
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


class DesktopAuthenticator(Protocol):
    def authenticate(self) -> Result[AuthSession]: ...


AuthControllerFactory = Callable[[AuthViewModel], DesktopAuthenticator]


_remember_session_store_instance: RememberSessionStore | None = None


def build_desktop_runtime(
    config: DesktopRuntimeConfig | None = None,
    *,
    argv: Sequence[str] | None = None,
) -> Result[DesktopRuntime]:
    config = config or DesktopRuntimeConfig()
    try:
        setup_logging()
        LOGGER.info("desktop_runtime_build_started")
        database_path, connection_factory, auth_repository = _prepare_database(config)
        user_result = _resolve_runtime_user(auth_repository, config)
        if not user_result.ok or user_result.value is None:
            return Result.failure(
                user_result.error
                or ValidationError("runtime_user_required", "runtime_user_required")
            )
        application = _application(argv)
        initialize_language(LanguagePreferences())
        job_runner = QtJobRunner(application)
        auth_view_model = _auth_view_model(auth_repository, connection_factory)
        remember_session_store = _remember_session_store()
        return _build_runtime_for_user(
            application=application,
            connection_factory=connection_factory,
            database_path=database_path,
            user=user_result.value,
            config=config,
            auth_repository=auth_repository,
            auth_view_model=auth_view_model,
            remember_session_store=remember_session_store,
            job_runner=job_runner,
        )
    except Exception as exc:
        LOGGER.exception("desktop_runtime_failed")
        return Result.failure(
            InfrastructureError(
                "desktop_runtime_failed",
                "desktop_runtime_failed",
                {"reason": str(exc)},
            )
        )


def build_authenticated_desktop_runtime(
    config: DesktopRuntimeConfig | None = None,
    *,
    argv: Sequence[str] | None = None,
    auth_controller_factory: AuthControllerFactory | None = None,
) -> Result[DesktopRuntime]:
    config = config or DesktopRuntimeConfig()
    try:
        setup_logging()
        LOGGER.info("authenticated_desktop_runtime_build_started")
        database_path, connection_factory, auth_repository = _prepare_database(config)
        application = _application(argv)
        initialize_language(LanguagePreferences())
        job_runner = QtJobRunner(application)
        auth_view_model = _auth_view_model(auth_repository, connection_factory)
        remember_session_store = _remember_session_store()
        authenticator = (
            auth_controller_factory(auth_view_model)
            if auth_controller_factory is not None
            else AuthController(
                auth_view_model,
                remember_session_store=remember_session_store,
            )
        )
        auth_result = authenticator.authenticate()
        if not auth_result.ok or auth_result.value is None:
            return Result.failure(
                auth_result.error or ValidationError("auth_required", "auth_required")
            )
        return _build_runtime_for_user(
            application=application,
            connection_factory=connection_factory,
            database_path=database_path,
            user=auth_result.value.user,
            config=config,
            auth_repository=auth_repository,
            auth_session=auth_result.value,
            auth_view_model=auth_view_model,
            remember_session_store=remember_session_store,
            job_runner=job_runner,
        )
    except Exception as exc:
        LOGGER.exception("desktop_runtime_failed")
        return Result.failure(
            InfrastructureError(
                "desktop_runtime_failed",
                "desktop_runtime_failed",
                {"reason": str(exc)},
            )
        )


def _application(argv: Sequence[str] | None) -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        configure_application_style()
        install_bundled_fonts()
        apply_application_icon()
        return existing
    application = QApplication(list(argv or []))
    application.setApplicationName(APP_NAME)
    application.setOrganizationName(APP_NAME)
    application.setApplicationVersion(APP_VERSION)
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    configure_application_style()
    install_bundled_fonts()
    apply_application_icon()
    return application


def _remember_session_store() -> RememberSessionStore:
    global _remember_session_store_instance
    if _remember_session_store_instance is None:
        _remember_session_store_instance = FileRememberTokenSessionStore()
    return _remember_session_store_instance


def _password_hasher(iterations: int | None) -> PBKDF2PasswordHasher:
    if iterations is None:
        return PBKDF2PasswordHasher()
    return PBKDF2PasswordHasher(iterations=int(iterations), legacy_iterations=(100,))


def _prepare_database(
    config: DesktopRuntimeConfig,
) -> tuple[Path, SQLiteConnectionFactory, RuntimeAuthRepository]:
    database_path = (
        Path(config.database_path) if config.database_path else default_database_path()
    )
    if (
        config.database_path is None
        and getattr(sys, "frozen", False)
        and not database_path.exists()
    ):
        previous = Path(sys.executable).resolve().parent / "worklog.db"
        if previous.is_file() and previous.resolve() != database_path.resolve():
            copy_database(previous, database_path)
    connection_factory = SQLiteConnectionFactory(database_path)
    if Path(str(database_path) + ".pre_restore").exists():
        raise ValueError("restore_pending")
    MigrationRunner(connection_factory).run_pending()
    protect_legacy_proxy_passwords(connection_factory, HmacSecretBox())
    auth_repository = SQLiteAuthRepository(
        connection_factory,
        password_hasher=_password_hasher(config.password_iterations),
    )
    return database_path, connection_factory, auth_repository


def _auth_view_model(
    auth_repository: AuthCredentialRepository,
    connection_factory: SQLiteConnectionFactory,
) -> AuthViewModel:
    return AuthViewModel(
        state_handler=GetAuthBootstrapStateHandler(auth_repository),
        login_handler=LoginHandler(
            auth_repository,
            SQLiteLoginFailureRepository(connection_factory),
        ),
        register_handler=RegisterUserHandler(auth_repository),
        change_password_handler=ChangePasswordHandler(auth_repository),
        remember_token_handler=LoginWithRememberTokenHandler(auth_repository),
        reset_password_handler=ResetPasswordHandler(auth_repository),
    )


def _build_runtime_for_user(
    *,
    application: QApplication,
    connection_factory: SQLiteConnectionFactory,
    database_path: Path,
    user: User,
    config: DesktopRuntimeConfig,
    auth_repository: RuntimeAuthRepository | None = None,
    auth_session: AuthSession | None = None,
    auth_view_model: AuthViewModel | None = None,
    remember_session_store: RememberSessionStore | None = None,
    job_runner: JobRunner | None = None,
) -> Result[DesktopRuntime]:
    repositories = _runtime_repositories(connection_factory)
    handlers = _runtime_handlers(repositories, holiday_country=detect_country())
    remember_store = remember_session_store or _remember_session_store()
    time_entry_view_model = _build_time_entry_view_model(user, repositories, handlers)
    settings_workflow = _build_settings_workflow(
        user=user,
        database_path=database_path,
        connection_factory=connection_factory,
        repositories=repositories,
        handlers=handlers,
        auth_repository=auth_repository,
        auth_view_model=auth_view_model,
        remember_session_store=remember_store,
        job_runner=job_runner,
        save_login_language=LanguagePreferences().save,
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
    preferences = LanguagePreferences()
    if preferences.load() is None and repositories.settings.get(
        user.id, LANGUAGE_SETTING_KEY
    ):
        preferences.save(state.language)
    time_entry_view_model.set_default_break_hours(state.default_break_hours)
    window_config = replace(
        window_config,
        theme=state.theme,
        dark=state.dark_mode,
        custom_color=state.custom_color,
        standard_work_hours=state.standard_work_hours,
        monthly_target_hours=state.monthly_target_hours,
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
                notes_workflow=_build_notes_workflow(
                    user, repositories, handlers, job_runner
                ),
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
            job_runner=job_runner,
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
        job_runner=job_runner,
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
    return replace(
        window_config,
        account_name=window_config.account_name or user.username,
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
) -> MinimalView:
    return MinimalView(
        time_entry_view_model=time_entry_view_model,
        config=MinimalViewConfig(
            selected_day=window_config.selected_day,
            today=window_config.today,
            account_name=window_config.account_name,
            confirm_discard_changes=window_config.confirm_discard_changes,
        ),
        settings_workflow=settings_workflow,
        notes_workflow=notes_workflow,
        residency_controller=residency_controller,
        job_runner=job_runner,
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
        ),
        config=window_config,
        settings_workflow=settings_workflow,
        analytics_workflow=_build_analytics_workflow(user, repositories),
        notes_workflow=_build_notes_workflow(user, repositories, handlers, job_runner),
        reports_workflow=_build_reports_workflow(user, repositories, handlers),
        residency_controller=residency_controller,
        job_runner=job_runner,
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
) -> Result[DesktopRuntime]:
    settings_workflow = getattr(window, "_settings_workflow", None)
    if settings_workflow is not None:
        settings_workflow.set_restore_handler(window.logout_requested.emit)
    return Result.success(
        DesktopRuntime(
            application=application,
            window=window,
            connection_factory=connection_factory,
            user=user,
            database_path=database_path,
            remember_session_store=remember_session_store,
            job_runner=job_runner,
            auth_session=auth_session,
        )
    )


def _minimal_mode_enabled(
    connection_factory: SQLiteConnectionFactory,
    user: User,
    config: DesktopRuntimeConfig,
) -> bool:
    if config.minimal_mode is not None:
        return bool(config.minimal_mode)
    settings = SQLiteSettingsRepository(connection_factory)
    return str(settings.get(user.id, MINIMAL_MODE_SETTING_KEY, "0")).strip() == "1"


def _resolve_runtime_user(
    auth_repository: RuntimeAuthRepository,
    config: DesktopRuntimeConfig,
) -> Result[User]:
    if config.user_id is not None:
        user = auth_repository.get_by_id(int(config.user_id))
        if user is None:
            return Result.failure(
                ValidationError("runtime_user_missing", "runtime_user_missing")
            )
        return Result.success(user)

    users = auth_repository.list_users()
    if users:
        return Result.success(users[0])

    if not config.create_user_if_empty:
        return Result.failure(
            ValidationError("runtime_user_required", "runtime_user_required")
        )

    username = _available_bootstrap_username(auth_repository, config.bootstrap_username)
    user = auth_repository.create_user(
        username,
        secrets.token_urlsafe(24),
        recovery_key=None,
        is_admin=True,
    )
    return Result.success(user)


def _available_bootstrap_username(
    auth_repository: RuntimeAuthRepository,
    username: str,
) -> str:
    base = str(username or "local").strip() or "local"
    candidate = base
    suffix = 1
    while auth_repository.get_by_username(candidate) is not None:
        suffix += 1
        candidate = f"{base}{suffix}"
    return candidate
