"""External identity use cases."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Protocol

from worklogger.app.commands.identity_commands import (
    LinkIdentityCommand,
    LoginWithIdentityCommand,
    UnlinkIdentityCommand,
)
from worklogger.app.queries.identity_queries import (
    GetIdentityProvidersQuery,
    ListLinkedIdentitiesQuery,
)
from worklogger.domain.auth.models import LinkedIdentity, User
from worklogger.domain.auth.repositories import AuthCredentialRepository, IdentityRepository
from worklogger.domain.identity.models import ExternalIdentityProfile, IdentityProviderStatus, normalize_provider
from worklogger.domain.auth.policies import username_key
from worklogger.domain.auth.policies import remember_token_expires_at, remember_token_storage_value
from worklogger.app.job_runner import CancellationToken
from worklogger.domain.shared.errors import AuthenticationError, InfrastructureError, ValidationError, CancellationError
from worklogger.domain.shared.result import Result
from worklogger.app.use_cases._errors import storage_boundary, infrastructure_failure


class IdentityProviderClient(Protocol):
    provider_id: str
    display_name: str

    def status(self) -> IdentityProviderStatus:
        ...

    def authenticate(self, *, cancellation: CancellationToken | None = None,
                     reauthenticate: bool = False) -> Result[ExternalIdentityProfile]:
        ...


@dataclass(frozen=True)
class IdentityProviderList:
    providers: tuple[IdentityProviderStatus, ...]


@dataclass(frozen=True)
class IdentityLoginResult:
    user: User
    linked_identity: LinkedIdentity
    token: str | None = None


class ListLinkedIdentitiesHandler:
    def __init__(self, repository: IdentityRepository) -> None:
        self._repository = repository

    @storage_boundary("identity_list_failed")
    def handle(
        self,
        query: ListLinkedIdentitiesQuery,
    ) -> Result[tuple[LinkedIdentity, ...]]:
        return Result.success(self._repository.list_for_user(query.user_id))


class GetIdentityProvidersHandler:
    def __init__(self, providers: tuple[IdentityProviderClient, ...]) -> None:
        self._providers = providers

    @storage_boundary("identity_list_failed")
    def handle(self, _query: GetIdentityProvidersQuery) -> Result[IdentityProviderList]:
        return Result.success(
            IdentityProviderList(
                providers=tuple(provider.status() for provider in self._providers)
            )
        )


class LinkIdentityHandler:
    def __init__(
        self,
        *,
        repository: IdentityRepository,
        providers: tuple[IdentityProviderClient, ...],
        auth: AuthCredentialRepository | None = None,
    ) -> None:
        self._repository = repository
        self._providers = {provider.provider_id: provider for provider in providers}
        self._auth = auth

    @storage_boundary("identity_link_failed")
    def handle(self, command: LinkIdentityCommand, *, cancellation=None) -> Result[LinkedIdentity]:
        authorized = _authorize_change(command, self._auth, self._repository, self._providers, cancellation)
        if not authorized.ok:
            return authorized
        provider = self._provider(command.provider)
        if not provider.ok or provider.value is None:
            return Result.failure(provider.error or _provider_missing_error())
        profile = _authenticate(provider.value, cancellation)
        if not profile.ok or profile.value is None:
            return Result.failure(
                profile.error
                or InfrastructureError(
                    "identity_auth_failed",
                    "identity_auth_failed",
                )
            )
        if cancellation and cancellation.is_cancelled():
            return _cancelled()
        try:
            existing = self._repository.get_by_provider_subject(profile.value.provider, profile.value.subject)
        except Exception as error:
            return Result.failure(infrastructure_failure("identity_link_failed", error, logger_name=__name__))
        if existing is not None and existing.user_id != command.user_id:
            return Result.failure(
                ValidationError(
                    "identity_already_linked",
                    "identity_already_linked",
                )
            )
        if existing is not None:
            if profile.value.issuer and existing.issuer != profile.value.issuer:
                return Result.failure(AuthenticationError("identity_issuer_mismatch", "identity_issuer_mismatch"))
            return Result.success(existing)
        if cancellation and cancellation.is_cancelled():
            return _cancelled()
        try:
            linked = self._repository.add(
                LinkedIdentity(
                    id=0,
                    user_id=command.user_id,
                    provider=profile.value.provider,
                    subject=profile.value.subject,
                    email=profile.value.email,
                    display_name=profile.value.display_name,
                    issuer=profile.value.issuer,
                )
            )
        except Exception as error:
            return Result.failure(infrastructure_failure("identity_link_failed", error, logger_name=__name__))
        return Result.success(linked)

    def _provider(self, provider_id: str) -> Result[IdentityProviderClient]:
        try:
            key = normalize_provider(provider_id)
        except ValueError as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        provider = self._providers.get(key)
        if provider is None:
            return Result.failure(_provider_missing_error())
        return Result.success(provider)


class UnlinkIdentityHandler:
    def __init__(self, repository: IdentityRepository, auth: AuthCredentialRepository | None = None,
                 *, providers: tuple[IdentityProviderClient, ...] = ()) -> None:
        self._repository = repository
        self._auth = auth
        self._providers = {provider.provider_id: provider for provider in providers}

    @storage_boundary("identity_unlink_failed")
    def handle(self, command: UnlinkIdentityCommand, *, cancellation=None) -> Result[None]:
        if command.identity_id <= 0:
            return Result.failure(ValidationError("identity_id_required", "identity_id_required"))
        identities = self._repository.list_for_user(command.user_id)
        if not any(identity.id == command.identity_id for identity in identities):
            return Result.failure(ValidationError("identity_missing", "identity_missing"))
        user = self._auth.get_by_id(command.user_id) if self._auth else None
        if len(identities) == 1 and (user is None or not user.local_password_enabled):
            return Result.failure(ValidationError("identity_last_login_method", "identity_last_login_method"))
        authorized = _authorize_change(command, self._auth, self._repository, self._providers, cancellation)
        if not authorized.ok:
            return authorized
        if cancellation and cancellation.is_cancelled():
            return _cancelled()
        self._repository.remove(command.user_id, command.identity_id)
        return Result.success(None)


class LoginWithIdentityHandler:
    def __init__(
        self,
        *,
        identities: IdentityRepository,
        auth: AuthCredentialRepository,
        providers: tuple[IdentityProviderClient, ...],
    ) -> None:
        self._identities = identities
        self._auth = auth
        self._providers = {provider.provider_id: provider for provider in providers}

    @storage_boundary("identity_login_failed")
    def handle(self, command: LoginWithIdentityCommand, *, cancellation=None) -> Result[IdentityLoginResult]:
        try:
            provider_key = normalize_provider(command.provider)
        except ValueError as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        provider = self._providers.get(provider_key)
        if provider is None:
            return Result.failure(ValidationError("identity_provider_missing", "identity_provider_missing"))
        profile = _authenticate(provider, cancellation)
        if not profile.ok or profile.value is None:
            return Result.failure(
                profile.error or AuthenticationError("identity_login_failed", "identity_login_failed")
            )
        if cancellation and cancellation.is_cancelled():
            return _cancelled()
        try:
            linked = self._identities.get_by_provider_subject(profile.value.provider, profile.value.subject)
        except Exception as error:
            return Result.failure(infrastructure_failure("identity_login_failed", error, logger_name=__name__))
        if linked is not None:
            if profile.value.issuer and linked.issuer != profile.value.issuer:
                return Result.failure(AuthenticationError("identity_issuer_mismatch", "identity_issuer_mismatch"))
            user = self._auth.get_by_id(linked.user_id)
            if user is None:
                return Result.failure(AuthenticationError("identity_user_missing", "identity_user_missing"))
            return self._session(user, linked, command.remember)
        base = _username_from_profile(profile.value)
        occupied = {username_key(user.username) for user in self._auth.list_users()}
        for _attempt in range(8):
            if cancellation and cancellation.is_cancelled():
                return _cancelled()
            username = base if username_key(base) not in occupied else f"{base}_{secrets.token_hex(6)}"
            creator = getattr(self._auth, "create_identity_account", None)
            if creator is None:
                return Result.failure(InfrastructureError("identity_login_failed", "identity_login_failed"))
            try:
                user, linked = creator(username, profile.value)
            except ValueError as exc:
                if str(exc) != "username_exists":
                    raise
                occupied.add(username_key(username))
                continue
            return self._session(user, linked, command.remember)
        return Result.failure(InfrastructureError("identity_login_failed", "identity_login_failed"))

    def _session(self, user, linked, remember):
        token = secrets.token_urlsafe(32) if remember and not user.must_change_password else None
        self._auth.set_remember_token(user.id, remember_token_storage_value(token) if token else None,
                                      remember_token_expires_at() if token else None)
        return Result.success(IdentityLoginResult(user, linked, token))


def _username_from_profile(profile: ExternalIdentityProfile) -> str:
    if profile.email and "@" in profile.email:
        base = profile.email.split("@", 1)[0]
    else:
        base = profile.display_name or f"{profile.provider}_{profile.subject}"
    cleaned = "".join(
        character if character.isalnum() or character in {"_", ".", "-"} else "_"
        for character in base.strip().lower()
    ).strip("._-")
    return cleaned[:107] or f"{profile.provider}_user"


def _provider_missing_error() -> ValidationError:
    return ValidationError("identity_provider_missing", "identity_provider_missing")


def _authorize_change(command, auth, identities, providers, cancellation):
    if cancellation and cancellation.is_cancelled():
        return _cancelled()
    user = auth.get_by_id(command.user_id) if auth is not None else None
    if user is None:
        return Result.failure(AuthenticationError("identity_user_missing", "identity_user_missing"))
    if user.local_password_enabled:
        if not command.current_password:
            return Result.failure(ValidationError("current_password_required", "current_password_required"))
        verified = auth.verify_user(user.username, command.current_password)
        if verified is None or verified.id != user.id:
            return Result.failure(AuthenticationError("invalid_credentials", "invalid_credentials"))
    else:
        linked = next((row for row in identities.list_for_user(user.id)
                       if row.id == command.verification_identity_id), None)
        provider = providers.get(linked.provider) if linked is not None else None
        if provider is None:
            return Result.failure(AuthenticationError("identity_auth_failed", "identity_auth_failed"))
        profile = provider.authenticate(cancellation=cancellation, reauthenticate=True)
        if not profile.ok or profile.value is None:
            return Result.failure(profile.error or AuthenticationError("identity_auth_failed", "identity_auth_failed"))
        if (profile.value.provider, profile.value.subject, profile.value.issuer) != (linked.provider, linked.subject, linked.issuer):
            return Result.failure(AuthenticationError("identity_issuer_mismatch", "identity_issuer_mismatch"))
        if linked not in identities.list_for_user(user.id):
            return Result.failure(AuthenticationError("identity_missing", "identity_missing"))
    return _cancelled() if cancellation and cancellation.is_cancelled() else Result.success(None)


def _authenticate(provider, cancellation):
    if cancellation and cancellation.is_cancelled():
        return _cancelled()
    return provider.authenticate(cancellation=cancellation) if cancellation is not None else provider.authenticate()


def _cancelled():
    return Result.failure(CancellationError("identity_authorization_cancelled", "identity_authorization_cancelled"))
