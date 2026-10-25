"""Runtime composition root for desktop presentation."""

from __future__ import annotations

import logging
from functools import lru_cache
import secrets
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from PySide6.QtWidgets import QApplication

from worklogger.__about__ import APP_ID, APP_NAME, APP_VERSION
from worklogger.app.use_cases.auth import (
    ChangePasswordHandler,
    GetAuthBootstrapStateHandler,
    LoginHandler,
    LoginWithRememberTokenHandler,
    RegisterUserHandler,
    ResetPasswordHandler,
)
from worklogger.app.use_cases.identity import GetIdentityProvidersHandler, LoginWithIdentityHandler
from worklogger.composition.context import (
    RuntimeAuthRepository,
)
from worklogger.composition.desktop import DesktopRuntime as DesktopRuntime
from worklogger.composition.desktop import DesktopRuntimeConfig as DesktopRuntimeConfig
from worklogger.composition.desktop import build_user_runtime
from worklogger.composition.identity import identity_providers
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
from worklogger.infrastructure.database.startup_recovery import startup_recovery_marker
from worklogger.infrastructure.database.upgrade import copy_database
from worklogger.infrastructure.identity.config import IdentityConfigurationStore
from worklogger.infrastructure.runtime_config import load_runtime_configuration
from worklogger.infrastructure.language_preferences import (
    LanguagePreferences,
    initialize_language,
)
from worklogger.infrastructure.logging import setup_logging
from worklogger.infrastructure.startup_errors import startup_error
from worklogger.infrastructure.repositories import (
    SQLiteAuthRepository,
    SQLiteIdentityRepository,
    SQLiteLoginFailureRepository,
)
from worklogger.infrastructure.security import (
    FileRememberTokenSessionStore,
    PBKDF2PasswordHasher,
)
from worklogger.infrastructure.security.key_store import (
    FernetSecretBox,
    protect_legacy_proxy_passwords,
)
from worklogger.presentation.auth import AuthController, AuthSession
from worklogger.presentation.auth.controller import RememberSessionStore
from worklogger.presentation.job_runner import QtJobRunner
from worklogger.presentation.input_behavior import install_input_behavior
from worklogger.presentation.theme import (
    configure_application_style,
    install_bundled_fonts,
)
from worklogger.presentation.viewmodels import (
    AuthViewModel,
)
from worklogger.presentation.widgets.assets import apply_application_icon

LOGGER = logging.getLogger(__name__)


class DesktopAuthenticator(Protocol):
    def authenticate(self) -> Result[AuthSession]: ...


AuthControllerFactory = Callable[[AuthViewModel], DesktopAuthenticator]



def build_desktop_runtime(
    config: DesktopRuntimeConfig | None = None,
    *,
    argv: Sequence[str] | None = None,
) -> Result[DesktopRuntime]:
    config = config or DesktopRuntimeConfig()
    job_runner = None
    runtime = None
    try:
        logging_result = _initialize_logging()
        if not logging_result.ok:
            return logging_result
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
        remember_session_store = _remember_session_store(database_path)
        runtime = build_user_runtime(
            application=application,
            connection_factory=connection_factory,
            database_path=database_path,
            user=user_result.value,
            config=config,
            auth_repository=auth_repository,
            auth_view_model=auth_view_model,
            remember_session_store=remember_session_store,
            language_preferences=LanguagePreferences(),
            holiday_country=detect_country(),
            job_runner=job_runner,
        )
        return runtime
    except Exception as exc:
        return _startup_failure(exc)
    finally:
        if job_runner is not None and (runtime is None or not runtime.ok):
            from worklogger.composition.lifecycle import stop_background_tasks
            stop_background_tasks(job_runner)
            job_runner.deleteLater()


def build_authenticated_desktop_runtime(
    config: DesktopRuntimeConfig | None = None,
    *,
    argv: Sequence[str] | None = None,
    auth_controller_factory: AuthControllerFactory | None = None,
) -> Result[DesktopRuntime]:
    config = config or DesktopRuntimeConfig()
    job_runner = None
    runtime = None
    try:
        logging_result = _initialize_logging()
        if not logging_result.ok:
            return logging_result
        LOGGER.info("authenticated_desktop_runtime_build_started")
        database_path, connection_factory, auth_repository = _prepare_database(config)
        application = _application(argv)
        initialize_language(LanguagePreferences())
        deployment = load_runtime_configuration()
        if not deployment.features.self_registration and auth_repository.user_count() == 0:
            code = "startup_account_setup_required" if deployment.valid else "startup_configuration_invalid"
            return Result.failure(InfrastructureError(code, code, {"resource": "configuration"}))
        job_runner = QtJobRunner(application)
        auth_view_model = _auth_view_model(auth_repository, connection_factory)
        remember_session_store = _remember_session_store(database_path)
        authenticator = (
            auth_controller_factory(auth_view_model)
            if auth_controller_factory is not None
            else AuthController(
                auth_view_model,
                job_runner=job_runner,
                remember_session_store=remember_session_store,
                allow_remembered_session=not config.skip_remembered_session,
            )
        )
        auth_result = authenticator.authenticate()
        if not auth_result.ok or auth_result.value is None:
            return Result.failure(
                auth_result.error or ValidationError("auth_required", "auth_required")
            )
        runtime = build_user_runtime(
            application=application,
            connection_factory=connection_factory,
            database_path=database_path,
            user=auth_result.value.user,
            config=config,
            auth_repository=auth_repository,
            auth_session=auth_result.value,
            auth_view_model=auth_view_model,
            remember_session_store=remember_session_store,
            language_preferences=LanguagePreferences(),
            holiday_country=detect_country(),
            job_runner=job_runner,
        )
        return runtime
    except Exception as exc:
        return _startup_failure(exc)
    finally:
        if job_runner is not None and (runtime is None or not runtime.ok):
            from worklogger.composition.lifecycle import stop_background_tasks
            stop_background_tasks(job_runner)
            job_runner.deleteLater()


def _initialize_logging():
    try:
        setup_logging()
        return Result.success(None)
    except OSError as error:
        return Result.failure(startup_error(error, fallback="startup_logging_failed", resource="logging"))


def _startup_failure(exc):
    LOGGER.exception("desktop_runtime_failed")
    return Result.failure(startup_error(exc))


def _application(argv: Sequence[str] | None) -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        install_input_behavior(existing)
        configure_application_style()
        install_bundled_fonts()
        apply_application_icon()
        return existing
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    application = QApplication(list(argv or []))
    application.setApplicationName(APP_NAME)
    application.setOrganizationName(APP_NAME)
    application.setApplicationVersion(APP_VERSION)
    install_input_behavior(application)
    configure_application_style()
    install_bundled_fonts()
    apply_application_icon()
    return application


def _remember_session_store(database_path) -> RememberSessionStore:
    from worklogger.infrastructure.security.session_store import session_path_for_database
    return _session_store(str(session_path_for_database(database_path)))


@lru_cache(maxsize=16)
def _session_store(path) -> RememberSessionStore:
    return FileRememberTokenSessionStore(Path(path))


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
    if startup_recovery_marker(database_path).exists():
        raise ValueError("startup_recovery_pending")
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
    try:
        protect_legacy_proxy_passwords(connection_factory, FernetSecretBox())
    except Exception as error:
        LOGGER.warning("proxy_credential_upgrade_deferred: %s", type(error).__name__)
    auth_repository = SQLiteAuthRepository(
        connection_factory,
        password_hasher=_password_hasher(config.password_iterations),
    )
    return database_path, connection_factory, auth_repository


def _auth_view_model(
    auth_repository: AuthCredentialRepository,
    connection_factory: SQLiteConnectionFactory,
) -> AuthViewModel:
    configuration = IdentityConfigurationStore()
    features = load_runtime_configuration().features
    providers = identity_providers(configuration=configuration, enabled=features.oidc)
    login_failures = SQLiteLoginFailureRepository(connection_factory)
    try:
        login_failures.prune()
    except Exception as error:
        LOGGER.warning("login_history_cleanup_failed: %s", type(error).__name__)
    return AuthViewModel(
        state_handler=GetAuthBootstrapStateHandler(auth_repository),
        login_handler=LoginHandler(
            auth_repository,
            login_failures,
        ),
        register_handler=RegisterUserHandler(auth_repository, enabled=features.self_registration),
        change_password_handler=ChangePasswordHandler(auth_repository, login_failures),
        remember_token_handler=LoginWithRememberTokenHandler(auth_repository),
        reset_password_handler=ResetPasswordHandler(auth_repository, SQLiteLoginFailureRepository(connection_factory, recovery=True)),
        identity_login_handler=LoginWithIdentityHandler(identities=SQLiteIdentityRepository(connection_factory),
            auth=auth_repository, providers=providers, enabled=features.oidc,
            self_registration_enabled=features.self_registration),
        identity_providers_handler=GetIdentityProvidersHandler(providers),
        identity_configuration=configuration,
        self_registration_enabled=features.self_registration,
        oidc_enabled=features.oidc,
    )


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
