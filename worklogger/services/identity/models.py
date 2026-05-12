from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

IdentityProvider = Literal["google", "microsoft"]
IdentityBroker = Literal["firebase", "direct_oidc"]


@dataclass(frozen=True)
class ExternalIdentity:
    provider: str
    broker: str
    issuer: str
    subject: str
    email: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    federated_subject: str | None = None
    raw_provider: str | None = None


@dataclass(frozen=True)
class OAuthTokens:
    id_token: str
    access_token: str | None = None
    refresh_token: str | None = None
    expires_in: int | None = None


@dataclass(frozen=True)
class IdentityAuthResult:
    identity: ExternalIdentity
    id_token: str | None = None
    refresh_token: str | None = None
    expires_in: int | None = None
