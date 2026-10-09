"""Desktop settings dependency composition."""

from __future__ import annotations

import hashlib
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
from worklogger.app.use_cases.settings import ProxyPasswordSettings
from worklogger.app.use_cases.updates import CheckForUpdatesHandler
from worklogger.app.use_cases.work_logs import (
    GetAllWorkLogsHandler,
)
from worklogger.app.use_cases.work_types import WorkTypeService
from worklogger.presentation.viewmodels.work_types import WorkTypeManagerViewModel
from worklogger.composition.context import (
    RuntimeAuthRepository,
    RuntimeHandlers,
    RuntimeRepositories,
)
from worklogger.composition.models import _build_local_models_workflow
from worklogger.config.constants import (
    GITHUB_LATEST_RELEASE_API_URL,
)
from worklogger.config.feature_flags import FeatureFlags
from worklogger.domain.auth.models import User
from worklogger.infrastructure.backup import SQLiteBackupService
from worklogger.infrastructure.calendar import (
    IcsCalendarImporter,
)
from worklogger.infrastructure.database import (
    SQLiteConnectionFactory,
)
from worklogger.infrastructure.export import (
    WorkLogCsvExporter,
    WorkLogCsvImporter,
    WorkLogIcsExporter,
)
from worklogger.infrastructure.i18n import get_language
from worklogger.infrastructure.identity import DisabledIdentityProvider
from worklogger.infrastructure.security.key_store import (
    EncryptedSettingsKeyStore,
    HmacSecretBox,
    SystemCredentialStore,
)
from worklogger.infrastructure.update import GitHubReleaseUpdateChecker
from worklogger.presentation.auth.controller import RememberSessionStore
from worklogger.presentation.identity import IdentityWorkflowController
from worklogger.presentation.settings import SettingsWorkflowController
from worklogger.presentation.viewmodels import (
    AuthViewModel,
    DataManagementViewModel,
    IdentityManagementViewModel,
    SettingsViewModel,
    UserManagementViewModel,
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
    job_runner: JobRunner | None,
    save_login_language,
) -> SettingsWorkflowController | None:
    if auth_view_model is None:
        return None
    features = FeatureFlags.from_env()
    return SettingsWorkflowController(
        settings_view_model=SettingsViewModel(
            user_id=user.id,
            get_handler=handlers.settings_get_handler,
            set_handler=handlers.settings_set_handler,
            default_language=get_language(),
            save_login_language=save_login_language,
            external_key_store=EncryptedSettingsKeyStore(
                repositories.settings,
                user_id=user.id,
                service_name="worklogger.external."
                + hashlib.sha256(
                    (str(database_path.resolve()) + ":" + str(user.id)).encode()
                ).hexdigest(),
            ),
            proxy_password_settings=ProxyPasswordSettings(
                repositories.settings,
                SystemCredentialStore(namespace=str(database_path.resolve())),
                user_id=user.id,
                secret_box=HmacSecretBox(),
            ),
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
        )
        if features.enable_update_check
        else None,
        job_runner=job_runner,
        identity_workflow=_build_identity_workflow(user, repositories, auth_repository),
        local_models_workflow=_build_local_models_workflow(
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
        ),
        remember_session_store=remember_session_store,
        work_types_view_model=WorkTypeManagerViewModel(WorkTypeService(user.id, repositories.work_types)),
        local_inference=handlers.local_inference,
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


def _build_identity_workflow(
    user: User,
    repositories: RuntimeRepositories,
    auth_repository: RuntimeAuthRepository | None,
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
            unlink_handler=UnlinkIdentityHandler(
                repositories.identities, auth_repository
            ),
        )
    )


def _identity_providers() -> tuple[DisabledIdentityProvider, ...]:
    return (
        DisabledIdentityProvider("google", "Google"),
        DisabledIdentityProvider("microsoft", "Microsoft"),
    )
