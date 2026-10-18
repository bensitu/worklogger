"""Identity presentation ViewModel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from worklogger.app.commands.identity_commands import LinkIdentityCommand, UnlinkIdentityCommand
from worklogger.app.queries.identity_queries import (
    GetIdentityProvidersQuery,
    ListLinkedIdentitiesQuery,
)
from worklogger.app.use_cases.identity import IdentityProviderList
from worklogger.domain.auth.models import LinkedIdentity
from worklogger.domain.identity.models import IdentityProviderStatus
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import _


class LinkedIdentitiesListHandler(Protocol):
    def handle(self, query: ListLinkedIdentitiesQuery) -> Result[tuple[LinkedIdentity, ...]]:
        ...


class IdentityProvidersHandler(Protocol):
    def handle(self, query: GetIdentityProvidersQuery) -> Result[IdentityProviderList]:
        ...


class IdentityLinkHandler(Protocol):
    def handle(self, command: LinkIdentityCommand) -> Result[LinkedIdentity]:
        ...


class IdentityUnlinkHandler(Protocol):
    def handle(self, command: UnlinkIdentityCommand) -> Result[None]:
        ...


@dataclass(frozen=True)
class IdentityManagementState:
    identities: tuple[LinkedIdentity, ...]
    providers: tuple[IdentityProviderStatus, ...]
    message: str = ""
    local_password_enabled: bool = True


class IdentityManagementViewModel:
    def __init__(
        self,
        *,
        user_id: int,
        list_handler: LinkedIdentitiesListHandler,
        providers_handler: IdentityProvidersHandler,
        link_handler: IdentityLinkHandler,
        unlink_handler: IdentityUnlinkHandler,
        local_password_enabled: bool = True,
    ) -> None:
        self._user_id = user_id
        self._list_handler = list_handler
        self._providers_handler = providers_handler
        self._link_handler = link_handler
        self._unlink_handler = unlink_handler
        self._local_password_enabled = local_password_enabled

    def load(self) -> Result[IdentityManagementState]:
        identities = self._list_handler.handle(ListLinkedIdentitiesQuery(self._user_id))
        if not identities.ok or identities.value is None:
            return Result.failure(
                identities.error or ValidationError("identity_load_failed", "identity_load_failed")
            )
        providers = self._providers_handler.handle(GetIdentityProvidersQuery(self._user_id))
        if not providers.ok or providers.value is None:
            return Result.failure(
                providers.error or ValidationError("identity_load_failed", "identity_load_failed")
            )
        return Result.success(
            IdentityManagementState(
                identities=identities.value,
                providers=providers.value.providers,
                local_password_enabled=self._local_password_enabled,
            )
        )

    def link(self, provider: str, *, current_password=None, verification_identity_id=None,
             cancellation=None) -> Result[IdentityManagementState]:
        command = LinkIdentityCommand(self._user_id, provider, current_password, verification_identity_id)
        linked = (self._link_handler.handle(command, cancellation=cancellation) if cancellation is not None
                  else self._link_handler.handle(command))
        if not linked.ok:
            return Result.failure(
                linked.error or ValidationError("identity_link_failed", "identity_link_failed")
            )
        return _with_message(self.load(), _("Identity linked."))

    def unlink(self, identity_id: int, *, current_password=None, verification_identity_id=None,
               cancellation=None) -> Result[IdentityManagementState]:
        command = UnlinkIdentityCommand(self._user_id, identity_id, current_password, verification_identity_id)
        unlinked = (self._unlink_handler.handle(command, cancellation=cancellation) if cancellation is not None
                    else self._unlink_handler.handle(command))
        if not unlinked.ok:
            return Result.failure(
                unlinked.error or ValidationError("identity_unlink_failed", "identity_unlink_failed")
            )
        return _with_message(self.load(), _("Identity unlinked."))


def _with_message(
    result: Result[IdentityManagementState],
    message: str,
) -> Result[IdentityManagementState]:
    if not result.ok or result.value is None:
        return result
    return Result.success(
        IdentityManagementState(
            identities=result.value.identities,
            providers=result.value.providers,
            message=message,
            local_password_enabled=result.value.local_password_enabled,
        )
    )
