"""Authentication use cases."""

from __future__ import annotations

import secrets
import math
from dataclasses import dataclass
from datetime import datetime, timezone

from worklogger.app.commands.auth_commands import (
    AdminResetPasswordCommand,
    ChangePasswordCommand,
    CreateManagedUserCommand,
    DeleteManagedUserCommand,
    LoginCommand,
    RegisterUserCommand,
    ResetPasswordCommand,
    SetPasswordChangeRequiredCommand,
)
from worklogger.app.queries.auth_queries import ListUsersQuery
from worklogger.domain.auth.models import RememberedLogin, User
from worklogger.domain.auth.policies import (
    generate_recovery_key,
    normalize_username,
    require_new_username,
    remember_token_expires_at,
    remember_token_storage_value,
    require_password,
)
from worklogger.domain.auth.repositories import (
    AuthCredentialRepository,
    LoginFailureRepository,
)
from worklogger.domain.shared.errors import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    InfrastructureError,
    NotFoundError,
    ValidationError,
)
from worklogger.domain.shared.result import Result
from worklogger.app.failures import storage_boundary


@dataclass(frozen=True)
class RegisteredUser:
    user: User
    recovery_key: str


@dataclass(frozen=True)
class AuthBootstrapState:
    has_users: bool


class GetAuthBootstrapStateHandler:
    def __init__(self, credentials: AuthCredentialRepository) -> None:
        self._credentials = credentials

    @storage_boundary("auth_state_failed")
    def handle(self) -> Result[AuthBootstrapState]:
        return Result.success(AuthBootstrapState(has_users=self._credentials.user_count() > 0))


class RegisterUserHandler:
    def __init__(self, credentials: AuthCredentialRepository, *, enabled: bool = True) -> None:
        self._credentials = credentials
        self._enabled = enabled

    @storage_boundary("auth_state_failed")
    def handle(self, command: RegisterUserCommand) -> Result[RegisteredUser]:
        if not self._enabled:
            return Result.failure(AuthorizationError("self_registration_disabled", "self_registration_disabled"))
        try:
            username = require_new_username(command.username)
            password = require_password(command.password)
            recovery_key = generate_recovery_key()
            user = self._credentials.register_user(
                username,
                password,
                recovery_key=recovery_key,
            )
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        return Result.success(RegisteredUser(user=user, recovery_key=recovery_key))


class LoginHandler:
    def __init__(
        self,
        credentials: AuthCredentialRepository,
        failures: LoginFailureRepository | None = None,
    ) -> None:
        self._credentials = credentials
        self._failures = failures

    @storage_boundary("auth_state_failed")
    def handle(self, command: LoginCommand) -> Result[RememberedLogin]:
        try:
            username = normalize_username(command.username)
            password = require_password(command.password, min_length=1, max_bytes=None)
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))

        remaining = _locked_seconds(self._failures, username)
        if remaining:
            self._credentials.verify_dummy_password(password)
            return Result.failure(AuthenticationError("account_locked", "account_locked", {"seconds": remaining}))

        user = self._credentials.verify_user(username, password)
        if user is None:
            if self._failures is not None:
                self._failures.record_failure(username)
            return Result.failure(AuthenticationError("invalid_credentials", "invalid_credentials"))

        if self._failures is not None:
            self._failures.clear_failures(username)

        remember_token: str | None = None
        if command.remember:
            remember_token = secrets.token_urlsafe(32)
            self._credentials.set_remember_token(
                user.id,
                remember_token_storage_value(remember_token),
                remember_token_expires_at(),
            )
        else:
            self._credentials.set_remember_token(user.id, None, None)
        return Result.success(RememberedLogin(user=user, token=remember_token))

class LoginWithRememberTokenHandler:
    def __init__(self, credentials: AuthCredentialRepository) -> None:
        self._credentials = credentials

    @storage_boundary("auth_state_failed")
    def handle(self, token: str) -> Result[User]:
        try:
            stored_token = remember_token_storage_value(token)
        except ValueError as exc:
            return Result.failure(AuthenticationError(str(exc), str(exc)))
        user = self._credentials.get_user_by_remember_token(stored_token)
        if user is None:
            return Result.failure(
                AuthenticationError("invalid_remember_token", "invalid_remember_token")
            )
        return Result.success(user)


class ChangePasswordHandler:
    def __init__(self, credentials: AuthCredentialRepository, failures: LoginFailureRepository | None = None) -> None:
        self._credentials = credentials
        self._failures = failures

    @storage_boundary("auth_state_failed")
    def handle(self, command: ChangePasswordCommand) -> Result[str]:
        try:
            current_password = require_password(
                command.current_password or "",
                field_name="current_password",
                min_length=1,
                max_bytes=None,
            )
            new_password = require_password(
                command.new_password,
                field_name="new_password",
            )
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        user = self._credentials.get_by_id(command.user_id)
        if user is None:
            return Result.failure(AuthenticationError("invalid_credentials", "invalid_credentials"))
        checked = verify_password_attempt(self._credentials, self._failures, user.username, current_password,
            lambda: self._credentials.change_password(command.user_id, current_password, new_password))
        if not checked.ok:
            return checked
        self._credentials.set_remember_token(command.user_id, None, None)
        return checked


class ResetPasswordHandler:
    def __init__(self, credentials: AuthCredentialRepository, failures: LoginFailureRepository | None = None) -> None:
        self._credentials = credentials
        self._failures = failures

    @storage_boundary("auth_state_failed")
    def handle(self, command: ResetPasswordCommand) -> Result[str]:
        try:
            username = normalize_username(command.username)
            recovery_key = require_password(
                command.recovery_key,
                field_name="recovery_key",
                min_length=1,
            )
            new_password = require_password(
                command.new_password,
                field_name="new_password",
            )
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        remaining = _locked_seconds(self._failures, username)
        if remaining:
            self._credentials.verify_dummy_password(recovery_key)
            return Result.failure(AuthenticationError("account_locked", "account_locked", {"seconds": remaining}))
        reset = self._credentials.reset_password_with_recovery(
            username,
            recovery_key,
            new_password,
        )
        if reset is None:
            if self._failures is not None:
                self._failures.record_failure(username)
            return Result.failure(
                AuthenticationError("invalid_recovery_key", "invalid_recovery_key")
            )
        user, new_recovery_key = reset
        if self._failures is not None:
            self._failures.clear_failures(username)
        self._credentials.set_remember_token(user.id, None, None)
        return Result.success(new_recovery_key)


class ListUsersHandler:
    def __init__(self, credentials: AuthCredentialRepository) -> None:
        self._credentials = credentials

    @storage_boundary("auth_state_failed")
    def handle(self, query: ListUsersQuery) -> Result[tuple[User, ...]]:
        admin = _require_admin(self._credentials, query.requesting_user_id)
        if not admin.ok:
            return Result.failure(
                admin.error or AuthorizationError("admin_required", "admin_required")
            )
        return Result.success(self._credentials.list_users())


class CreateManagedUserHandler:
    def __init__(self, credentials: AuthCredentialRepository) -> None:
        self._credentials = credentials

    @storage_boundary("auth_state_failed")
    def handle(self, command: CreateManagedUserCommand) -> Result[RegisteredUser]:
        admin = _require_admin(self._credentials, command.requesting_user_id)
        if not admin.ok:
            return Result.failure(
                admin.error or AuthorizationError("admin_required", "admin_required")
            )
        try:
            username = require_new_username(command.username)
            password = require_password(command.password)
            recovery_key = generate_recovery_key()
            user = self._credentials.create_user(
                username,
                password,
                recovery_key=recovery_key,
                is_admin=bool(command.is_admin),
                must_change_password=bool(command.must_change_password),
            )
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        return Result.success(RegisteredUser(user=user, recovery_key=recovery_key))


class AdminResetPasswordHandler:
    def __init__(self, credentials: AuthCredentialRepository) -> None:
        self._credentials = credentials

    @storage_boundary("auth_state_failed")
    def handle(self, command: AdminResetPasswordCommand) -> Result[str]:
        admin = _require_admin(self._credentials, command.requesting_user_id)
        if not admin.ok:
            return Result.failure(
                admin.error or AuthorizationError("admin_required", "admin_required")
            )
        if self._credentials.get_by_id(command.target_user_id) is None:
            return Result.failure(NotFoundError("user_not_found", "user_not_found"))
        try:
            password = require_password(command.new_password, field_name="new_password")
        except (TypeError, ValueError) as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        reset_password = self._credentials.reset_password_by_admin(
            command.target_user_id,
            password,
            must_change_password=True,
        )
        if reset_password is None:
            return Result.failure(NotFoundError("user_not_found", "user_not_found"))
        self._credentials.set_remember_token(command.target_user_id, None, None)
        return Result.success(password)


class SetPasswordChangeRequiredHandler:
    def __init__(self, credentials: AuthCredentialRepository) -> None:
        self._credentials = credentials

    @storage_boundary("auth_state_failed")
    def handle(self, command: SetPasswordChangeRequiredCommand) -> Result[User]:
        admin = _require_admin(self._credentials, command.requesting_user_id)
        if not admin.ok:
            return Result.failure(
                admin.error or AuthorizationError("admin_required", "admin_required")
            )
        target = self._credentials.get_by_id(command.target_user_id)
        if target is None:
            return Result.failure(NotFoundError("user_not_found", "user_not_found"))
        changed = self._credentials.set_password_change_required(
            command.target_user_id,
            bool(command.required),
        )
        if not changed:
            return Result.failure(NotFoundError("user_not_found", "user_not_found"))
        if command.required:
            self._credentials.set_remember_token(command.target_user_id, None, None)
        updated = self._credentials.get_by_id(command.target_user_id)
        return Result.success(updated or target)


class DeleteManagedUserHandler:
    def __init__(self, credentials: AuthCredentialRepository, *, cleanup_credentials=None) -> None:
        self._credentials = credentials
        self._cleanup_credentials = cleanup_credentials

    @storage_boundary("auth_state_failed")
    def handle(self, command: DeleteManagedUserCommand) -> Result[None]:
        admin = _require_admin(self._credentials, command.requesting_user_id)
        if not admin.ok or admin.value is None:
            return Result.failure(
                admin.error or AuthorizationError("admin_required", "admin_required")
            )
        target = self._credentials.get_by_id(command.target_user_id)
        if target is None:
            if self._cleanup_credentials is not None and command.target_user_id != admin.value.id:
                return self._cleanup_credentials(command.target_user_id)
            return Result.failure(NotFoundError("user_not_found", "user_not_found"))
        if target.id == admin.value.id:
            return Result.failure(ConflictError("cannot_delete_self", "cannot_delete_self"))
        if target.is_admin and _admin_count(self._credentials.list_users()) <= 1:
            return Result.failure(
                ConflictError("cannot_delete_last_admin", "cannot_delete_last_admin")
            )
        if not self._credentials.delete_user(target.id):
            return Result.failure(NotFoundError("user_not_found", "user_not_found"))
        if self._cleanup_credentials is not None:
            cleared = self._cleanup_credentials(target.id)
            if not cleared.ok:
                return Result.failure(cleared.error or InfrastructureError("credential_storage_unavailable", "credential_storage_unavailable"))
        return Result.success(None)


def _require_admin(
    credentials: AuthCredentialRepository,
    requesting_user_id: int,
) -> Result[User]:
    user = credentials.get_by_id(requesting_user_id)
    if user is None or not user.is_admin:
        return Result.failure(AuthorizationError("admin_required", "admin_required"))
    return Result.success(user)


def _admin_count(users: tuple[User, ...]) -> int:
    return sum(1 for user in users if user.is_admin)


def _locked_seconds(failures, username):
    until = failures.lockout_until(username) if failures is not None else None
    if until is None:
        return 0
    return max(0, math.ceil((until.replace(tzinfo=until.tzinfo or timezone.utc) - datetime.now(timezone.utc)).total_seconds()))


def verify_password_attempt(credentials, failures, username, password, verify):
    remaining = _locked_seconds(failures, username)
    if remaining:
        credentials.verify_dummy_password(password)
        return Result.failure(AuthenticationError("account_locked", "account_locked", {"seconds": remaining}))
    value = verify()
    if value is None:
        if failures is not None:
            failures.record_failure(username)
        return Result.failure(AuthenticationError("invalid_credentials", "invalid_credentials"))
    if failures is not None:
        failures.clear_failures(username)
    return Result.success(value)


class RevokeRememberedSessionHandler:
    def __init__(self, credentials: AuthCredentialRepository, *, user_id: int):
        self._credentials = credentials
        self._user_id = user_id

    @storage_boundary("auth_state_failed")
    def handle(self) -> Result[None]:
        self._credentials.set_remember_token(self._user_id, None, None)
        return Result.success(None)
