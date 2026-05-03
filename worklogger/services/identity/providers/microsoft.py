from __future__ import annotations

from ..errors import IdentityProviderUnavailable


class MicrosoftProvider:
    provider_name = "microsoft"

    def build_authorization_url(self, **_kwargs) -> str:
        raise IdentityProviderUnavailable("identity_provider_unavailable")

    def exchange_code_for_tokens(self, **_kwargs):
        raise IdentityProviderUnavailable("identity_provider_unavailable")
