"""External identity domain models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExternalIdentityProfile:
    provider: str
    subject: str
    email: str | None = None
    display_name: str | None = None
    issuer: str = ""
    broker: str = ""
    federated_subject: str = ""
    raw_provider: str = ""


@dataclass(frozen=True)
class IdentityProviderStatus:
    provider: str
    display_name: str
    available: bool
    configured: bool
    message: str = ""
