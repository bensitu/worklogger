"""External identity use cases."""

from __future__ import annotations

import hashlib
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
from worklogger.domain.auth.policies import generate_initial_password, username_key
from worklogger.domain.shared.errors import AuthenticationError, InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result


class IdentityProviderClient(Protocol):
    provider_id: str
    display_name: str

    def status(self) -> IdentityProviderStatus:
        ...

    def authenticate(self) -> Result[ExternalIdentityProfile]:
        ...


@dataclass(frozen=True)
class IdentityProviderList:
    providers: tuple[IdentityProviderStatus, ...]


@dataclass(frozen=True)
class IdentityLoginResult:
    user: User
    linked_identity: LinkedIdentity


class ListLinkedIdentitiesHandler:
    def __init__(self, repository: IdentityRepository) -> None:
        self._repository = repository

    def handle(
        self,
        query: ListLinkedIdentitiesQuery,
    ) -> Result[tuple[LinkedIdentity, ...]]:
        return Result.success(self._repository.list_for_user(query.user_id))


class GetIdentityProvidersHandler:
    def __init__(self, providers: tuple[IdentityProviderClient, ...]) -> None:
        self._providers = providers

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
    ) -> None:
        self._repository = repository
        self._providers = {provider.provider_id: provider for provider in providers}

    def handle(self, command: LinkIdentityCommand) -> Result[LinkedIdentity]:
        provider = self._provider(command.provider)
        if not provider.ok or provider.value is None:
            return Result.failure(provider.error or _provider_missing_error())
        profile = provider.value.authenticate()
        if not profile.ok or profile.value is None:
            return Result.failure(
                profile.error
                or InfrastructureError(
                    "identity_auth_failed",
                    "identity_auth_failed",
                )
            )
        try:
            existing = self._repository.get_by_provider_subject(profile.value.provider, profile.value.subject)
        except Exception:
            return Result.failure(AuthenticationError("identity_login_failed", "identity_login_failed"))
        if existing is not None and existing.user_id != command.user_id:
            return Result.failure(
                ValidationError(
                    "identity_already_linked",
                    "identity_already_linked",
                )
            )
        if existing is not None:
            return Result.success(existing)
        try:
            linked = self._repository.add(
                LinkedIdentity(
                    id=0,
                    user_id=command.user_id,
                    provider=profile.value.provider,
                    subject=profile.value.subject,
                    email=profile.value.email,
                    display_name=profile.value.display_name,
                )
            )
        except Exception as exc:
            return Result.failure(
                InfrastructureError(
                    "identity_link_failed",
                    "identity_link_failed",
                    {"reason": str(exc)},
                )
            )
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
    def __init__(self, repository: IdentityRepository, auth: AuthCredentialRepository | None = None) -> None:
        self._repository = repository
        self._auth = auth

    def handle(self, command: UnlinkIdentityCommand) -> Result[None]:
        if command.identity_id <= 0:
            return Result.failure(ValidationError("identity_id_required", "identity_id_required"))
        identities = self._repository.list_for_user(command.user_id)
        if not any(identity.id == command.identity_id for identity in identities):
            return Result.failure(ValidationError("identity_missing", "identity_missing"))
        user = self._auth.get_by_id(command.user_id) if self._auth else None
        if len(identities) == 1 and (user is None or not user.local_password_enabled):
            return Result.failure(ValidationError("identity_last_login_method", "identity_last_login_method"))
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

    def handle(self, command: LoginWithIdentityCommand) -> Result[IdentityLoginResult]:
        try:
            provider_key = normalize_provider(command.provider)
        except ValueError as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        provider = self._providers.get(provider_key)
        if provider is None:
            return Result.failure(ValidationError("identity_provider_missing", "identity_provider_missing"))
        profile = provider.authenticate()
        if not profile.ok or profile.value is None:
            return Result.failure(
                profile.error or AuthenticationError("identity_login_failed", "identity_login_failed")
            )
        try:
            linked = self._identities.get_by_provider_subject(profile.value.provider, profile.value.subject)
        except Exception:
            return Result.failure(AuthenticationError("identity_login_failed", "identity_login_failed"))
        if linked is not None:
            user = self._auth.get_by_id(linked.user_id)
            if user is None:
                return Result.failure(AuthenticationError("identity_user_missing", "identity_user_missing"))
            return Result.success(IdentityLoginResult(user=user, linked_identity=linked))
        base = _username_from_profile(profile.value)
        occupied = {username_key(user.username) for user in self._auth.list_users()}
        suffix = hashlib.sha256(f"{profile.value.provider}:{profile.value.issuer}:{profile.value.subject}".encode()).hexdigest()[:12]
        username = base if username_key(base) not in occupied else f"{base}_{suffix}"
        user = None
        try:
            user = self._auth.create_user(
                username, generate_initial_password(), recovery_key=None, is_admin=False,
                must_change_password=False, local_password_enabled=False,
            )
            linked = self._identities.add(
                LinkedIdentity(id=0, user_id=user.id, provider=profile.value.provider,
                               subject=profile.value.subject, email=profile.value.email,
                               display_name=profile.value.display_name)
            )
        except Exception:
            if user is not None:
                self._auth.delete_user(user.id)
            return Result.failure(InfrastructureError("identity_login_failed", "identity_login_failed"))
        return Result.success(IdentityLoginResult(user=user, linked_identity=linked))


def _username_from_profile(profile: ExternalIdentityProfile) -> str:
    if profile.email and "@" in profile.email:
        base = profile.email.split("@", 1)[0]
    else:
        base = profile.display_name or f"{profile.provider}_{profile.subject}"
    cleaned = "".join(
        character if character.isalnum() or character in {"_", ".", "-"} else "_"
        for character in base.strip().lower()
    ).strip("._-")
    return cleaned or f"{profile.provider}_user"


def _provider_missing_error() -> ValidationError:
    return ValidationError("identity_provider_missing", "identity_provider_missing")
