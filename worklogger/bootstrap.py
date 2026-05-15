"""Runtime composition root for desktop presentation."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
import secrets
from typing import Protocol

from PySide6.QtWidgets import QApplication

from worklogger.app.use_cases.analytics import GetAnalyticsBundleHandler
from worklogger.app.use_cases.ai import (
    AiChatHandler,
    BuildAiContextHandler,
    RewriteTextHandler,
)
from worklogger.app.use_cases.auth import (
    AdminResetPasswordHandler,
    ChangePasswordHandler,
    CreateManagedUserHandler,
    DeleteManagedUserHandler,
    GetAuthBootstrapStateHandler,
    LoginHandler,
    LoginWithRememberTokenHandler,
    ListUsersHandler,
    RegisterUserHandler,
    ResetPasswordHandler,
    SetPasswordChangeRequiredHandler,
)
from worklogger.app.use_cases.calendar import (
    GetCalendarEventsForDayHandler,
    GetCalendarEventsForRangeHandler,
    GetHolidaysForRangeHandler,
    ImportCalendarEventsHandler,
)
from worklogger.app.use_cases.data_portability import ImportWorkLogsCsvHandler
from worklogger.app.use_cases.identity import (
    GetIdentityProvidersHandler,
    LinkIdentityHandler,
    ListLinkedIdentitiesHandler,
    UnlinkIdentityHandler,
)
from worklogger.app.use_cases.local_models import (
    DeleteLocalModelHandler,
    DownloadLocalModelHandler,
    ImportLocalModelHandler,
    ListLocalModelsHandler,
    RefreshLocalModelCatalogHandler,
    SelectLocalModelHandler,
    VerifyLocalModelHandler,
)
from worklogger.app.use_cases.notes import GetDailyNoteHandler, SaveDailyNoteHandler
from worklogger.app.use_cases.quick_logs import (
    AddQuickLogHandler,
    DeleteQuickLogHandler,
    GetQuickLogsForDayHandler,
    GetQuickLogsForRangeHandler,
    UpdateQuickLogHandler,
)
from worklogger.app.use_cases.reports import (
    GenerateReportHandler,
    GetReportForPeriodHandler,
    ResetReportTemplateHandler,
    SaveReportHandler,
    SaveReportTemplateHandler,
)
from worklogger.app.use_cases.work_logs import (
    GetAllWorkLogsHandler,
    GetMonthRecordsHandler,
    GetWorkLogHandler,
    SaveWorkLogHandler,
)
from worklogger.app.use_cases.settings import GetSettingHandler, SetSettingHandler
from worklogger.app.use_cases.updates import CheckForUpdatesHandler
from worklogger.config.constants import (
    GITHUB_LATEST_RELEASE_API_URL,
    MINIMAL_MODE_SETTING_KEY,
)
from worklogger.domain.auth.repositories import AuthCredentialRepository
from worklogger.domain.auth.models import User
from worklogger.domain.shared.errors import InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.database import (
    MigrationRunner,
    SQLiteConnectionFactory,
    default_database_path,
)
from worklogger.infrastructure.backup import SQLiteBackupService
from worklogger.infrastructure.calendar import (
    IcsCalendarImporter,
    PythonHolidaysProvider,
    detect_country,
)
from worklogger.infrastructure.export import (
    AnalyticsCsvExporter,
    AnalyticsPdfExporter,
    MarkdownExporter,
    WorkLogCsvExporter,
    WorkLogCsvImporter,
    WorkLogIcsExporter,
)
from worklogger.infrastructure.identity import DisabledIdentityProvider
from worklogger.infrastructure.local_model import JsonLocalModelStore
from worklogger.infrastructure.repositories import (
    SQLiteAuthRepository,
    SQLiteCalendarEventRepository,
    SQLiteDailyNoteRepository,
    SQLiteIdentityRepository,
    SQLiteLoginFailureRepository,
    SQLiteQuickLogRepository,
    SQLiteReportRepository,
    SQLiteReportTemplateRepository,
    SQLiteSettingsRepository,
    SQLiteWorkLogRepository,
)
from worklogger.infrastructure.security import (
    FileRememberTokenSessionStore,
    PBKDF2PasswordHasher,
)
from worklogger.infrastructure.templates import BuiltInTemplateProvider, UserTemplateProvider
from worklogger.infrastructure.update import GitHubReleaseUpdateChecker
from worklogger.presentation.ai import AiAssistWorkflowController
from worklogger.presentation.analytics import AnalyticsWorkflowController
from worklogger.presentation.auth import AuthController, AuthSession
from worklogger.presentation.auth.controller import RememberSessionStore
from worklogger.presentation.identity import IdentityWorkflowController
from worklogger.presentation.local_models import LocalModelsWorkflowController
from worklogger.presentation.notes import NotesWorkflowController
from worklogger.presentation.quick_logs import QuickLogsWorkflowController
from worklogger.presentation.reporting import ReportsWorkflowController
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
    AiAssistViewModel,
    AnalyticsViewModel,
    CalendarViewModel,
    DataManagementViewModel,
    IdentityManagementViewModel,
    LocalModelManagerViewModel,
    NoteEditorViewModel,
    QuickLogEditorViewModel,
    ReportEditorViewModel,
    StatsPanelViewModel,
    SettingsViewModel,
    UserManagementViewModel,
    WorkLogEntryViewModel,
)


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
    auth_session: AuthSession | None = None


class DesktopAuthenticator(Protocol):
    def authenticate(self) -> Result[AuthSession]:
        ...


AuthControllerFactory = Callable[[AuthViewModel], DesktopAuthenticator]


class RuntimeAuthRepository(AuthCredentialRepository, Protocol):
    def get_by_username(self, username: str) -> User | None:
        ...


_remember_session_store_instance: RememberSessionStore | None = None


def build_desktop_runtime(
    config: DesktopRuntimeConfig | None = None,
    *,
    argv: Sequence[str] | None = None,
) -> Result[DesktopRuntime]:
    config = config or DesktopRuntimeConfig()
    try:
        database_path, connection_factory, auth_repository = _prepare_database(config)
        user_result = _resolve_runtime_user(auth_repository, config)
        if not user_result.ok or user_result.value is None:
            return Result.failure(
                user_result.error
                or ValidationError("runtime_user_required", "runtime_user_required")
            )
        application = _application(argv)
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
        )
    except Exception as exc:
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
        database_path, connection_factory, auth_repository = _prepare_database(config)
        application = _application(argv)
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
        )
    except Exception as exc:
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
        return existing
    return QApplication(list(argv or []))


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
    database_path = Path(config.database_path) if config.database_path else default_database_path()
    connection_factory = SQLiteConnectionFactory(database_path)
    MigrationRunner(connection_factory).run_pending()
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


@dataclass(frozen=True)
class RuntimeRepositories:
    work_logs: SQLiteWorkLogRepository
    calendar_events: SQLiteCalendarEventRepository
    daily_notes: SQLiteDailyNoteRepository
    identities: SQLiteIdentityRepository
    quick_logs: SQLiteQuickLogRepository
    reports: SQLiteReportRepository
    report_templates: SQLiteReportTemplateRepository
    settings: SQLiteSettingsRepository


@dataclass(frozen=True)
class RuntimeHandlers:
    templates: UserTemplateProvider
    markdown_exporter: MarkdownExporter
    rewrite_handler: RewriteTextHandler
    ai_chat_handler: AiChatHandler
    save_template_handler: SaveReportTemplateHandler
    reset_template_handler: ResetReportTemplateHandler
    settings_get_handler: GetSettingHandler
    settings_set_handler: SetSettingHandler
    month_records_handler: GetMonthRecordsHandler
    holiday_provider: PythonHolidaysProvider
    holiday_country: str


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
) -> Result[DesktopRuntime]:
    repositories = _runtime_repositories(connection_factory)
    handlers = _runtime_handlers(repositories)
    remember_store = remember_session_store or _remember_session_store()
    worklog_entry_view_model = _build_worklog_entry_view_model(user, repositories)
    settings_workflow = _build_settings_workflow(
        user=user,
        database_path=database_path,
        connection_factory=connection_factory,
        repositories=repositories,
        handlers=handlers,
        auth_repository=auth_repository,
        auth_view_model=auth_view_model,
        remember_session_store=remember_store,
    )
    residency_controller = _build_residency_controller(user, handlers)
    window_config = _window_config_for_user(config.window, user)

    if _minimal_mode_enabled(connection_factory, user, config):
        return _runtime_result(
            application=application,
            window=_build_minimal_view(
                worklog_entry_view_model=worklog_entry_view_model,
                window_config=window_config,
                settings_workflow=settings_workflow,
                residency_controller=residency_controller,
            ),
            connection_factory=connection_factory,
            database_path=database_path,
            user=user,
            remember_session_store=remember_store,
            auth_session=auth_session,
        )

    return _runtime_result(
        application=application,
        window=_build_app_window(
            user=user,
            repositories=repositories,
            handlers=handlers,
            worklog_entry_view_model=worklog_entry_view_model,
            window_config=window_config,
            settings_workflow=settings_workflow,
            residency_controller=residency_controller,
        ),
        connection_factory=connection_factory,
        database_path=database_path,
        user=user,
        remember_session_store=remember_store,
        auth_session=auth_session,
    )


def _runtime_repositories(
    connection_factory: SQLiteConnectionFactory,
) -> RuntimeRepositories:
    return RuntimeRepositories(
        work_logs=SQLiteWorkLogRepository(connection_factory),
        calendar_events=SQLiteCalendarEventRepository(connection_factory),
        daily_notes=SQLiteDailyNoteRepository(connection_factory),
        identities=SQLiteIdentityRepository(connection_factory),
        quick_logs=SQLiteQuickLogRepository(connection_factory),
        reports=SQLiteReportRepository(connection_factory),
        report_templates=SQLiteReportTemplateRepository(connection_factory),
        settings=SQLiteSettingsRepository(connection_factory),
    )


def _runtime_handlers(repositories: RuntimeRepositories) -> RuntimeHandlers:
    return RuntimeHandlers(
        templates=UserTemplateProvider(
            repositories.report_templates,
            BuiltInTemplateProvider(),
        ),
        markdown_exporter=MarkdownExporter(),
        rewrite_handler=RewriteTextHandler(),
        ai_chat_handler=AiChatHandler(),
        save_template_handler=SaveReportTemplateHandler(repositories.report_templates),
        reset_template_handler=ResetReportTemplateHandler(repositories.report_templates),
        settings_get_handler=GetSettingHandler(repositories.settings),
        settings_set_handler=SetSettingHandler(repositories.settings),
        month_records_handler=GetMonthRecordsHandler(repositories.work_logs),
        holiday_provider=PythonHolidaysProvider(),
        holiday_country=detect_country(),
    )


def _build_worklog_entry_view_model(
    user: User,
    repositories: RuntimeRepositories,
) -> WorkLogEntryViewModel:
    return WorkLogEntryViewModel(
        user_id=user.id,
        get_handler=GetWorkLogHandler(repositories.work_logs),
        save_handler=SaveWorkLogHandler(repositories.work_logs),
    )


def _build_quick_logs_workflow(
    user: User,
    repositories: RuntimeRepositories,
) -> QuickLogsWorkflowController:
    return QuickLogsWorkflowController(
        QuickLogEditorViewModel(
            user_id=user.id,
            add_handler=AddQuickLogHandler(repositories.quick_logs),
            update_handler=UpdateQuickLogHandler(repositories.quick_logs),
            delete_handler=DeleteQuickLogHandler(repositories.quick_logs),
            get_day_handler=GetQuickLogsForDayHandler(repositories.quick_logs),
        )
    )


def _build_analytics_workflow(
    user: User,
    repositories: RuntimeRepositories,
) -> AnalyticsWorkflowController:
    return AnalyticsWorkflowController(
        AnalyticsViewModel(
            user_id=user.id,
            bundle_handler=GetAnalyticsBundleHandler(repositories.work_logs),
            csv_exporter=AnalyticsCsvExporter(),
            pdf_exporter=AnalyticsPdfExporter(),
        )
    )


def _build_ai_workflow(
    user: User,
    repositories: RuntimeRepositories,
    handlers: RuntimeHandlers,
) -> AiAssistWorkflowController:
    return AiAssistWorkflowController(
        AiAssistViewModel(
            user_id=user.id,
            chat_handler=handlers.ai_chat_handler,
            context_handler=BuildAiContextHandler(
                work_logs_handler=GetAllWorkLogsHandler(repositories.work_logs),
                note_handler=GetDailyNoteHandler(repositories.daily_notes),
                quick_logs_handler=GetQuickLogsForRangeHandler(repositories.quick_logs),
                calendar_events_handler=GetCalendarEventsForRangeHandler(
                    repositories.calendar_events
                ),
                settings_handler=handlers.settings_get_handler,
            ),
        )
    )


def _build_notes_workflow(
    user: User,
    repositories: RuntimeRepositories,
    handlers: RuntimeHandlers,
) -> NotesWorkflowController:
    return NotesWorkflowController(
        NoteEditorViewModel(
            user_id=user.id,
            get_note_handler=GetDailyNoteHandler(repositories.daily_notes),
            save_note_handler=SaveDailyNoteHandler(repositories.daily_notes),
            quick_logs_handler=GetQuickLogsForDayHandler(repositories.quick_logs),
            calendar_events_handler=GetCalendarEventsForDayHandler(
                repositories.calendar_events
            ),
            templates=handlers.templates,
            save_template_handler=handlers.save_template_handler,
            reset_template_handler=handlers.reset_template_handler,
            markdown_exporter=handlers.markdown_exporter,
            rewrite_handler=handlers.rewrite_handler,
        )
    )


def _build_reports_workflow(
    user: User,
    repositories: RuntimeRepositories,
    handlers: RuntimeHandlers,
) -> ReportsWorkflowController:
    return ReportsWorkflowController(
        ReportEditorViewModel(
            user_id=user.id,
            generate_handler=GenerateReportHandler(
                work_logs=repositories.work_logs,
                quick_logs=repositories.quick_logs,
                calendar_events=repositories.calendar_events,
                templates=handlers.templates,
            ),
            get_report_handler=GetReportForPeriodHandler(repositories.reports),
            save_report_handler=SaveReportHandler(repositories.reports),
            save_template_handler=handlers.save_template_handler,
            reset_template_handler=handlers.reset_template_handler,
            markdown_exporter=handlers.markdown_exporter,
            rewrite_handler=handlers.rewrite_handler,
        )
    )


def _build_settings_workflow(
    *,
    user: User,
    database_path: Path,
    connection_factory: SQLiteConnectionFactory,
    repositories: RuntimeRepositories,
    handlers: RuntimeHandlers,
    auth_repository: RuntimeAuthRepository | None,
    auth_view_model: AuthViewModel | None,
    remember_session_store: RememberSessionStore,
) -> SettingsWorkflowController | None:
    if auth_view_model is None:
        return None
    return SettingsWorkflowController(
        settings_view_model=SettingsViewModel(
            user_id=user.id,
            get_handler=handlers.settings_get_handler,
            set_handler=handlers.settings_set_handler,
        ),
        auth_view_model=auth_view_model,
        user=user,
        data_management_view_model=_build_data_management_view_model(
            user=user,
            connection_factory=connection_factory,
            repositories=repositories,
        ),
        update_check_handler=CheckForUpdatesHandler(
            GitHubReleaseUpdateChecker(api_url=GITHUB_LATEST_RELEASE_API_URL)
        ),
        identity_workflow=_build_identity_workflow(user, repositories),
        local_models_workflow=_build_local_models_workflow(
            user=user,
            database_path=database_path,
            repositories=repositories,
        ),
        user_management_view_model=_build_user_management_view_model(
            user,
            auth_repository,
        ),
        remember_session_store=remember_session_store,
    )


def _build_data_management_view_model(
    *,
    user: User,
    connection_factory: SQLiteConnectionFactory,
    repositories: RuntimeRepositories,
) -> DataManagementViewModel:
    return DataManagementViewModel(
        user_id=user.id,
        work_logs_handler=GetAllWorkLogsHandler(repositories.work_logs),
        backup_service=SQLiteBackupService(
            connection_factory,
            expected_username=user.username,
        ),
        csv_exporter=WorkLogCsvExporter(),
        ics_exporter=WorkLogIcsExporter(),
        csv_import_handler=ImportWorkLogsCsvHandler(
            importer=WorkLogCsvImporter(),
            repository=repositories.work_logs,
        ),
        calendar_events_handler=GetCalendarEventsForRangeHandler(
            repositories.calendar_events
        ),
        ics_import_handler=ImportCalendarEventsHandler(
            repositories.calendar_events,
            IcsCalendarImporter(),
        ),
    )


def _build_user_management_view_model(
    user: User,
    auth_repository: RuntimeAuthRepository | None,
) -> UserManagementViewModel | None:
    if auth_repository is None:
        return None
    return UserManagementViewModel(
        requesting_user_id=user.id,
        list_users_handler=ListUsersHandler(auth_repository),
        create_user_handler=CreateManagedUserHandler(auth_repository),
        reset_password_handler=AdminResetPasswordHandler(auth_repository),
        set_password_change_required_handler=SetPasswordChangeRequiredHandler(
            auth_repository
        ),
        delete_user_handler=DeleteManagedUserHandler(auth_repository),
    )


def _build_local_models_workflow(
    *,
    user: User,
    database_path: Path,
    repositories: RuntimeRepositories,
) -> LocalModelsWorkflowController:
    local_model_store = JsonLocalModelStore(database_path.parent / "models")
    return LocalModelsWorkflowController(
        LocalModelManagerViewModel(
            user_id=user.id,
            list_handler=ListLocalModelsHandler(
                store=local_model_store,
                settings=repositories.settings,
            ),
            refresh_handler=RefreshLocalModelCatalogHandler(local_model_store),
            import_handler=ImportLocalModelHandler(
                store=local_model_store,
                settings=repositories.settings,
            ),
            download_handler=DownloadLocalModelHandler(
                store=local_model_store,
                settings=repositories.settings,
            ),
            verify_handler=VerifyLocalModelHandler(local_model_store),
            select_handler=SelectLocalModelHandler(
                store=local_model_store,
                settings=repositories.settings,
            ),
            delete_handler=DeleteLocalModelHandler(
                store=local_model_store,
                settings=repositories.settings,
                usage_reader=repositories.settings,
            ),
        )
    )


def _build_identity_workflow(
    user: User,
    repositories: RuntimeRepositories,
) -> IdentityWorkflowController:
    identity_providers = _identity_providers()
    return IdentityWorkflowController(
        IdentityManagementViewModel(
            user_id=user.id,
            list_handler=ListLinkedIdentitiesHandler(repositories.identities),
            providers_handler=GetIdentityProvidersHandler(identity_providers),
            link_handler=LinkIdentityHandler(
                repository=repositories.identities,
                providers=identity_providers,
            ),
            unlink_handler=UnlinkIdentityHandler(repositories.identities),
        )
    )


def _identity_providers() -> tuple[DisabledIdentityProvider, ...]:
    return (
        DisabledIdentityProvider("google", "Google"),
        DisabledIdentityProvider("microsoft", "Microsoft"),
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
    if window_config.account_name:
        return window_config
    return replace(window_config, account_name=user.username)


def _build_minimal_view(
    *,
    worklog_entry_view_model: WorkLogEntryViewModel,
    window_config: AppWindowConfig,
    settings_workflow: SettingsWorkflowController | None,
    residency_controller: QtResidencyController,
) -> MinimalView:
    return MinimalView(
        worklog_entry_view_model=worklog_entry_view_model,
        config=MinimalViewConfig(
            selected_day=window_config.selected_day,
            today=window_config.today,
            account_name=window_config.account_name,
            confirm_discard_changes=window_config.confirm_discard_changes,
        ),
        settings_workflow=settings_workflow,
        residency_controller=residency_controller,
    )


def _build_app_window(
    *,
    user: User,
    repositories: RuntimeRepositories,
    handlers: RuntimeHandlers,
    worklog_entry_view_model: WorkLogEntryViewModel,
    window_config: AppWindowConfig,
    settings_workflow: SettingsWorkflowController | None,
    residency_controller: QtResidencyController,
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
        ),
        worklog_entry_view_model=worklog_entry_view_model,
        stats_panel_view_model=StatsPanelViewModel(
            user_id=user.id,
            month_records_handler=handlers.month_records_handler,
        ),
        config=window_config,
        settings_workflow=settings_workflow,
        quick_logs_workflow=_build_quick_logs_workflow(user, repositories),
        analytics_workflow=_build_analytics_workflow(user, repositories),
        ai_assist_workflow=_build_ai_workflow(user, repositories, handlers),
        notes_workflow=_build_notes_workflow(user, repositories, handlers),
        reports_workflow=_build_reports_workflow(user, repositories, handlers),
        residency_controller=residency_controller,
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
) -> Result[DesktopRuntime]:
    return Result.success(
        DesktopRuntime(
            application=application,
            window=window,
            connection_factory=connection_factory,
            user=user,
            database_path=database_path,
            remember_session_store=remember_session_store,
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
            return Result.failure(ValidationError("runtime_user_missing", "runtime_user_missing"))
        return Result.success(user)

    users = auth_repository.list_users()
    if users:
        return Result.success(users[0])

    if not config.create_user_if_empty:
        return Result.failure(ValidationError("runtime_user_required", "runtime_user_required"))

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
