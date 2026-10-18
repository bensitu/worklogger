"""Desktop settings dependency composition."""

from __future__ import annotations

from pathlib import Path

from worklogger.app.job_runner import JobRunner
from worklogger.app.use_cases.auth import (
    AdminResetPasswordHandler,
    CreateManagedUserHandler,
    DeleteManagedUserHandler,
    ListUsersHandler,
    SetPasswordChangeRequiredHandler,
)
from worklogger.app.use_cases.calendar import (
    GetCalendarEventsForRangeHandler,
    ImportCalendarEventsHandler,
)
from worklogger.app.use_cases.data_portability import ImportWorkLogsCsvHandler
from worklogger.app.use_cases.identity import (
    GetIdentityProvidersHandler,
    LinkIdentityHandler,
    ListLinkedIdentitiesHandler,
    UnlinkIdentityHandler,
)
from worklogger.app.use_cases.projects import ProjectService
from worklogger.app.use_cases.updates import CheckForUpdatesHandler
from worklogger.app.use_cases.user_profile import UserProfileService
from worklogger.app.use_cases.work_logs import (
    GetAllWorkLogsHandler,
)
from worklogger.app.use_cases.entry_types import EntryTypeService
from worklogger.composition.context import (
    RuntimeAuthRepository,
    RuntimeHandlers,
    RuntimeRepositories,
)
from worklogger.composition.identity import identity_providers
from worklogger.composition.models import build_local_models_workflow
from worklogger.config.constants import (
    GITHUB_LATEST_RELEASE_API_URL,
)
from worklogger.config.feature_flags import FeatureFlags
from worklogger.domain.auth.models import User
from worklogger.infrastructure.backup import SQLiteBackupService
from worklogger.infrastructure.calendar import (
    IcsCalendarImporter,
)
from worklogger.infrastructure.calendar.holidays_provider import detect_country, supported_holiday_regions
from worklogger.infrastructure.database import (
    SQLiteConnectionFactory,
)
from worklogger.infrastructure.export import (
    WorkLogCsvExporter,
    WorkLogCsvImporter,
    WorkLogIcsExporter,
)
from worklogger.infrastructure.i18n import get_language
from worklogger.infrastructure.identity.config import IdentityConfigurationStore
from worklogger.infrastructure.runtime_config import load_runtime_configuration
from worklogger.infrastructure.security.account_credentials import cleanup_account_credentials
from worklogger.infrastructure.update import GitHubReleaseUpdateChecker
from worklogger.presentation.auth.controller import RememberSessionStore
from worklogger.presentation.identity import IdentityWorkflowController
from worklogger.presentation.settings import SettingsWorkflowController
from worklogger.presentation.settings_capabilities import SettingsCapabilities
from worklogger.presentation.viewmodels import (
    AuthViewModel,
    DataManagementViewModel,
    IdentityManagementViewModel,
    SettingsViewModel,
    UserManagementViewModel,
)
from worklogger.presentation.viewmodels.projects import ProjectManagerViewModel
from worklogger.presentation.viewmodels.classifications import ClassificationManagerViewModel
from worklogger.app.use_cases.work_modes import WorkModeService
from worklogger.app.use_cases.cloud_backups import CloudBackupService
from worklogger.infrastructure.backup.archive import PersonalBackupArchive
from worklogger.infrastructure.backup.configuration import CloudBackupConfigurationStore
from worklogger.infrastructure.backup.object_stores import backup_store
from worklogger.infrastructure.backup.personal_data import SQLitePersonalData
from worklogger.infrastructure.backup.recovery import PersonalRecoveryStore
from worklogger.infrastructure.security.key_store import SystemCredentialStore


def build_settings_workflow(
    *,
    user: User,
    database_path: Path,
    connection_factory: SQLiteConnectionFactory,
    repositories: RuntimeRepositories,
    handlers: RuntimeHandlers,
    auth_repository: RuntimeAuthRepository | None,
    auth_view_model: AuthViewModel | None,
    remember_session_store: RememberSessionStore,
    job_runner: JobRunner | None,
    save_login_language,
) -> SettingsWorkflowController | None:
    if auth_view_model is None:
        return None
    features = FeatureFlags.from_env()
    runtime_configuration = load_runtime_configuration()
    return SettingsWorkflowController(
        settings_view_model=SettingsViewModel(
            user_id=user.id,
            get_handler=handlers.settings_get_handler,
            set_handler=handlers.settings_set_handler,
            default_language=get_language(),
            save_login_language=save_login_language,
            external_key_store=handlers.external_keys,
            proxy_password_settings=handlers.proxy_password,
            holiday_regions=supported_holiday_regions,
            system_holiday_country=detect_country,
        ),
        auth_view_model=auth_view_model,
        database_path=database_path,
        user=user,
        profile_service=UserProfileService(user_id=user.id, repository=auth_repository) if auth_repository is not None else None,
        data_management_view_model=_build_data_management_view_model(
            user=user,
            connection_factory=connection_factory,
            repositories=repositories,
        ),
        update_check_handler=CheckForUpdatesHandler(
            GitHubReleaseUpdateChecker(api_url=GITHUB_LATEST_RELEASE_API_URL,
                opener=handlers.network_transport.opener(public_only=True) if handlers.network_transport else None)
        )
        if features.enable_update_check
        else None,
        job_runner=job_runner,
        identity_workflow=_build_identity_workflow(user, repositories, auth_repository, job_runner=job_runner,
            opener=handlers.network_transport.opener(public_only=True, allow_redirects=False) if handlers.network_transport else None),
        local_models_workflow=build_local_models_workflow(
            user=user,
            database_path=database_path,
            repositories=repositories,
            job_runner=job_runner,
            store=handlers.local_inference.store if handlers.local_inference else None,
            before_delete=handlers.local_inference.release_model if handlers.local_inference else None,
        )
        if features.enable_local_models
        else None,
        user_management_view_model=_build_user_management_view_model(
            user,
            auth_repository,
            database_path=database_path,
        ),
        remember_session_store=remember_session_store,
        entry_types_view_model=ClassificationManagerViewModel(EntryTypeService(user.id, repositories.entry_types)),
        work_modes_view_model=ClassificationManagerViewModel(WorkModeService(user.id, repositories.work_modes)),
        projects_view_model=ProjectManagerViewModel(ProjectService(user.id, repositories.projects)),
        local_inference=handlers.local_inference,
        ai_gateway=handlers.ai_gateway,
        ai_connection_test_timeout_seconds=runtime_configuration.ai.connection_test_timeout_seconds,
        capabilities=SettingsCapabilities(external_generation=features.enable_ai,
            proxy_routing=handlers.network_transport is not None, model_management=features.enable_local_models,
            minimal_view=runtime_configuration.features.minimal_view),
        cloud_backup_startup_delay_seconds=runtime_configuration.cloud_backup.startup_delay_seconds,
        cloud_backup_check_interval_seconds=runtime_configuration.cloud_backup.check_interval_seconds,
        cloud_backup_retry_initial_seconds=runtime_configuration.cloud_backup.retry_initial_seconds,
        cloud_backup_retry_max_seconds=runtime_configuration.cloud_backup.retry_max_seconds,
        cloud_backup_service=CloudBackupService(
            configuration=CloudBackupConfigurationStore(repositories.settings,
                SystemCredentialStore(namespace=str(database_path.resolve())), user.id),
            personal_data=SQLitePersonalData(connection_factory, user.id, expected_username=user.username), archive=PersonalBackupArchive(),
            store_factory=lambda configuration, credentials: backup_store(configuration, credentials,
                opener=handlers.network_transport.opener(allow_redirects=False) if handlers.network_transport else None,
                proxy_url=handlers.network_transport.proxy_url() if handlers.network_transport else None),
            recovery_store=PersonalRecoveryStore(database_path.parent / "personal-recovery" / str(user.id))),
    )


def _build_data_management_view_model(
    *,
    user: User,
    connection_factory: SQLiteConnectionFactory,
    repositories: RuntimeRepositories,
) -> DataManagementViewModel:
    return DataManagementViewModel(
        user_id=user.id,
        can_manage_database=user.is_admin,
        work_logs_handler=GetAllWorkLogsHandler(
            repositories.work_logs, include_note_only=True
        ),
        backup_service=SQLiteBackupService(
            connection_factory,
            expected_username=user.username,
            requesting_user_id=user.id,
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
    *, database_path,
) -> UserManagementViewModel | None:
    if auth_repository is None or not user.is_admin:
        return None
    return UserManagementViewModel(
        requesting_user_id=user.id,
        list_users_handler=ListUsersHandler(auth_repository),
        create_user_handler=CreateManagedUserHandler(auth_repository),
        reset_password_handler=AdminResetPasswordHandler(auth_repository),
        set_password_change_required_handler=SetPasswordChangeRequiredHandler(
            auth_repository
        ),
        delete_user_handler=DeleteManagedUserHandler(auth_repository, cleanup_credentials=lambda user_id:
            cleanup_account_credentials(user_id, database_path)),
    )


def _build_identity_workflow(
    user: User,
    repositories: RuntimeRepositories,
    auth_repository: RuntimeAuthRepository | None,
    *, job_runner=None, opener=None,
) -> IdentityWorkflowController:
    configuration = IdentityConfigurationStore()
    providers = identity_providers(configuration=configuration, opener=opener)
    return IdentityWorkflowController(
        IdentityManagementViewModel(
            user_id=user.id,
            list_handler=ListLinkedIdentitiesHandler(repositories.identities),
            providers_handler=GetIdentityProvidersHandler(providers),
            link_handler=LinkIdentityHandler(
                repository=repositories.identities,
                providers=providers,
            ),
            unlink_handler=UnlinkIdentityHandler(
                repositories.identities, auth_repository
            ),
        ), configuration=configuration, job_runner=job_runner,
    )
