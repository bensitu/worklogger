"""Identity infrastructure adapters."""

from worklogger.infrastructure.identity.config import (
    identity_enabled,
    provider_available,
    provider_configured,
)
from worklogger.infrastructure.identity.oidc import (
    OidcAuthorizationBuilder,
    google_oidc_config,
    microsoft_oidc_config,
    profile_from_firebase_google_response,
    profile_from_oidc_claims,
)
from worklogger.infrastructure.identity.pkce import build_code_challenge, generate_verifier
from worklogger.infrastructure.identity.providers import DisabledIdentityProvider

__all__ = [
    "DisabledIdentityProvider",
    "OidcAuthorizationBuilder",
    "build_code_challenge",
    "generate_verifier",
    "google_oidc_config",
    "identity_enabled",
    "microsoft_oidc_config",
    "provider_available",
    "provider_configured",
    "profile_from_firebase_google_response",
    "profile_from_oidc_claims",
]
