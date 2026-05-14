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
from worklogger.config.constants import MINIMAL_MODE_SETTING_KEY
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
    auth_session: AuthSession | None = None


class DesktopAuthenticator(Protocol):
    def authenticate(self) -> Result[AuthSession]:
        ...


AuthControllerFactory = Callable[[AuthViewModel], DesktopAuthenticator]


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
        return _build_runtime_for_user(
            application=application,
            connection_factory=connection_factory,
            database_path=database_path,
            user=user_result.value,
            config=config,
            auth_repository=auth_repository,
            auth_view_model=auth_view_model,
            remember_session_store=FileRememberTokenSessionStore(),
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
        remember_session_store = FileRememberTokenSessionStore()
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


def _password_hasher(iterations: int | None) -> PBKDF2PasswordHasher:
    if iterations is None:
        return PBKDF2PasswordHasher()
    return PBKDF2PasswordHasher(iterations=int(iterations), legacy_iterations=(100,))


def _prepare_database(
    config: DesktopRuntimeConfig,
) -> tuple[Path, SQLiteConnectionFactory, SQLiteAuthRepository]:
    database_path = Path(config.database_path) if config.database_path else default_database_path()
    connection_factory = SQLiteConnectionFactory(database_path)
    MigrationRunner(connection_factory).run_pending()
    auth_repository = SQLiteAuthRepository(
        connection_factory,
        password_hasher=_password_hasher(config.password_iterations),
    )
    return database_path, connection_factory, auth_repository


def _auth_view_model(
    auth_repository: SQLiteAuthRepository,
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
    auth_repository: SQLiteAuthRepository | None = None,
    auth_session: AuthSession | None = None,
    auth_view_model: AuthViewModel | None = None,
    remember_session_store: FileRememberTokenSessionStore | None = None,
) -> Result[DesktopRuntime]:
    work_logs = SQLiteWorkLogRepository(connection_factory)
    calendar_events = SQLiteCalendarEventRepository(connection_factory)
    daily_notes = SQLiteDailyNoteRepository(connection_factory)
    identities = SQLiteIdentityRepository(connection_factory)
    quick_logs = SQLiteQuickLogRepository(connection_factory)
    reports = SQLiteReportRepository(connection_factory)
    report_templates = SQLiteReportTemplateRepository(connection_factory)
    templates = UserTemplateProvider(report_templates, BuiltInTemplateProvider())
    markdown_exporter = MarkdownExporter()
    rewrite_handler = RewriteTextHandler()
    ai_chat_handler = AiChatHandler()
    save_template_handler = SaveReportTemplateHandler(report_templates)
    reset_template_handler = ResetReportTemplateHandler(report_templates)
    holiday_provider = PythonHolidaysProvider()
    holiday_country = detect_country()
    settings_repository = SQLiteSettingsRepository(connection_factory)
    local_model_store = JsonLocalModelStore(database_path.parent / "models")
    identity_providers = (
        DisabledIdentityProvider("google", "Google"),
        DisabledIdentityProvider("microsoft", "Microsoft"),
    )
    settings_get_handler = GetSettingHandler(settings_repository)
    settings_set_handler = SetSettingHandler(settings_repository)
    month_records_handler = GetMonthRecordsHandler(work_logs)
    worklog_entry_view_model = WorkLogEntryViewModel(
        user_id=user.id,
        get_handler=GetWorkLogHandler(work_logs),
        save_handler=SaveWorkLogHandler(work_logs),
    )
    quick_logs_workflow = QuickLogsWorkflowController(
        QuickLogEditorViewModel(
            user_id=user.id,
            add_handler=AddQuickLogHandler(quick_logs),
            update_handler=UpdateQuickLogHandler(quick_logs),
            delete_handler=DeleteQuickLogHandler(quick_logs),
            get_day_handler=GetQuickLogsForDayHandler(quick_logs),
        )
    )
    analytics_workflow = AnalyticsWorkflowController(
        AnalyticsViewModel(
            user_id=user.id,
            bundle_handler=GetAnalyticsBundleHandler(work_logs),
            csv_exporter=AnalyticsCsvExporter(),
            pdf_exporter=AnalyticsPdfExporter(),
        )
    )
    ai_assist_workflow = AiAssistWorkflowController(
        AiAssistViewModel(
            user_id=user.id,
            chat_handler=ai_chat_handler,
            context_handler=BuildAiContextHandler(
                work_logs_handler=GetAllWorkLogsHandler(work_logs),
                note_handler=GetDailyNoteHandler(daily_notes),
                quick_logs_handler=GetQuickLogsForRangeHandler(quick_logs),
                calendar_events_handler=GetCalendarEventsForRangeHandler(calendar_events),
                settings_handler=settings_get_handler,
            ),
        )
    )
    notes_workflow = NotesWorkflowController(
        NoteEditorViewModel(
            user_id=user.id,
            get_note_handler=GetDailyNoteHandler(daily_notes),
            save_note_handler=SaveDailyNoteHandler(daily_notes),
            quick_logs_handler=GetQuickLogsForDayHandler(quick_logs),
            calendar_events_handler=GetCalendarEventsForDayHandler(calendar_events),
            templates=templates,
            save_template_handler=save_template_handler,
            reset_template_handler=reset_template_handler,
            markdown_exporter=markdown_exporter,
            rewrite_handler=rewrite_handler,
        )
    )
    reports_workflow = ReportsWorkflowController(
        ReportEditorViewModel(
            user_id=user.id,
            generate_handler=GenerateReportHandler(
                work_logs=work_logs,
                quick_logs=quick_logs,
                calendar_events=calendar_events,
                templates=templates,
            ),
            get_report_handler=GetReportForPeriodHandler(reports),
            save_report_handler=SaveReportHandler(reports),
            save_template_handler=save_template_handler,
            reset_template_handler=reset_template_handler,
            markdown_exporter=markdown_exporter,
            rewrite_handler=rewrite_handler,
        )
    )
    settings_workflow = None
    if auth_view_model is not None:
        user_management_view_model = None
        if auth_repository is not None:
            user_management_view_model = UserManagementViewModel(
                requesting_user_id=user.id,
                list_users_handler=ListUsersHandler(auth_repository),
                create_user_handler=CreateManagedUserHandler(auth_repository),
                reset_password_handler=AdminResetPasswordHandler(auth_repository),
                set_password_change_required_handler=SetPasswordChangeRequiredHandler(
                    auth_repository
                ),
                delete_user_handler=DeleteManagedUserHandler(auth_repository),
            )
        local_models_workflow = LocalModelsWorkflowController(
            LocalModelManagerViewModel(
                user_id=user.id,
                list_handler=ListLocalModelsHandler(
                    store=local_model_store,
                    settings=settings_repository,
                ),
                refresh_handler=RefreshLocalModelCatalogHandler(local_model_store),
                import_handler=ImportLocalModelHandler(
                    store=local_model_store,
                    settings=settings_repository,
                ),
                download_handler=DownloadLocalModelHandler(
                    store=local_model_store,
                    settings=settings_repository,
                ),
                verify_handler=VerifyLocalModelHandler(local_model_store),
                select_handler=SelectLocalModelHandler(
                    store=local_model_store,
                    settings=settings_repository,
                ),
                delete_handler=DeleteLocalModelHandler(
                    store=local_model_store,
                    settings=settings_repository,
                    usage_reader=settings_repository,
                ),
            )
        )
        identity_workflow = IdentityWorkflowController(
            IdentityManagementViewModel(
                user_id=user.id,
                list_handler=ListLinkedIdentitiesHandler(identities),
                providers_handler=GetIdentityProvidersHandler(identity_providers),
                link_handler=LinkIdentityHandler(
                    repository=identities,
                    providers=identity_providers,
                ),
                unlink_handler=UnlinkIdentityHandler(identities),
            )
        )
        settings_workflow = SettingsWorkflowController(
            settings_view_model=SettingsViewModel(
                user_id=user.id,
                get_handler=settings_get_handler,
                set_handler=settings_set_handler,
            ),
            auth_view_model=auth_view_model,
            user=user,
            data_management_view_model=DataManagementViewModel(
                user_id=user.id,
                work_logs_handler=GetAllWorkLogsHandler(work_logs),
                backup_service=SQLiteBackupService(
                    connection_factory,
                    expected_username=user.username,
                ),
                csv_exporter=WorkLogCsvExporter(),
                ics_exporter=WorkLogIcsExporter(),
                csv_import_handler=ImportWorkLogsCsvHandler(
                    importer=WorkLogCsvImporter(),
                    repository=work_logs,
                ),
                calendar_events_handler=GetCalendarEventsForRangeHandler(calendar_events),
                ics_import_handler=ImportCalendarEventsHandler(
                    calendar_events,
                    IcsCalendarImporter(),
                ),
            ),
            update_check_handler=CheckForUpdatesHandler(
                GitHubReleaseUpdateChecker(
                    api_url="https://api.github.com/repos/bensitu/worklogger/releases/latest",
                )
            ),
            identity_workflow=identity_workflow,
            local_models_workflow=local_models_workflow,
            user_management_view_model=user_management_view_model,
            remember_session_store=remember_session_store,
        )
    residency_controller = QtResidencyController(
        ResidencyViewModel(
            user_id=user.id,
            get_handler=settings_get_handler,
            set_handler=settings_set_handler,
        )
    )

    window_config = config.window
    if not window_config.account_name:
        window_config = replace(window_config, account_name=user.username)

    if _minimal_mode_enabled(connection_factory, user, config):
        minimal_window = MinimalView(
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
        return Result.success(
            DesktopRuntime(
                application=application,
                window=minimal_window,
                connection_factory=connection_factory,
                user=user,
                database_path=database_path,
                auth_session=auth_session,
            )
        )

    app_window = AppWindow(
        calendar_view_model=CalendarViewModel(
            user_id=user.id,
            month_records_handler=month_records_handler,
            calendar_events_handler=GetCalendarEventsForRangeHandler(calendar_events),
            holidays_handler=GetHolidaysForRangeHandler(holiday_provider),
            holiday_country=holiday_country,
        ),
        worklog_entry_view_model=worklog_entry_view_model,
        stats_panel_view_model=StatsPanelViewModel(
            user_id=user.id,
            month_records_handler=month_records_handler,
        ),
        config=window_config,
        settings_workflow=settings_workflow,
        quick_logs_workflow=quick_logs_workflow,
        analytics_workflow=analytics_workflow,
        ai_assist_workflow=ai_assist_workflow,
        notes_workflow=notes_workflow,
        reports_workflow=reports_workflow,
        residency_controller=residency_controller,
    )
    return Result.success(
        DesktopRuntime(
            application=application,
            window=app_window,
            connection_factory=connection_factory,
            user=user,
            database_path=database_path,
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
    auth_repository: SQLiteAuthRepository,
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
    auth_repository: SQLiteAuthRepository,
    username: str,
) -> str:
    base = str(username or "local").strip() or "local"
    candidate = base
    suffix = 1
    while auth_repository.get_by_username(candidate) is not None:
        suffix += 1
        candidate = f"{base}{suffix}"
    return candidate
