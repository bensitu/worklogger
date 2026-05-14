"""Identity provider adapters."""

from __future__ import annotations

from worklogger.domain.identity.models import ExternalIdentityProfile, IdentityProviderStatus
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.identity.config import (
    normalize_provider,
    provider_available,
    provider_configured,
)


class DisabledIdentityProvider:
    def __init__(
        self,
        provider_id: str,
        display_name: str,
        *,
        message: str = "identity_provider_not_configured",
    ) -> None:
        self.provider_id = normalize_provider(provider_id)
        self.display_name = display_name
        self._message = message

    def status(self) -> IdentityProviderStatus:
        configured = provider_configured(self.provider_id)
        available = provider_available(self.provider_id)
        return IdentityProviderStatus(
            provider=self.provider_id,
            display_name=self.display_name,
            available=available,
            configured=configured,
            message="" if available else self._message,
        )

    def authenticate(self) -> Result[ExternalIdentityProfile]:
        return Result.failure(InfrastructureError(self._message, self._message))
