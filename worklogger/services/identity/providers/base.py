from __future__ import annotations

from typing import Protocol

from ..models import OAuthTokens


class IdentityProviderProtocol(Protocol):
    provider_name: str

    def build_authorization_url(self, **kwargs) -> str:
        ...

    def exchange_code_for_tokens(self, **kwargs) -> OAuthTokens:
        ...
