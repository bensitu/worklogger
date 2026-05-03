"""Compatibility shim for pre-v3.2 OAuth imports.

New code should use ``services.identity``. This module intentionally keeps only
small wrappers needed by older tests or plugins that still import OAuth names.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from services.identity import config as identity_config
from services.identity.errors import IdentityError, IdentityStateMismatch, IdentityTokenInvalid
from services.identity.models import ExternalIdentity
from services.identity.pkce import build_code_challenge
from services.identity.token_validation import validate_oidc_id_token


@dataclass(frozen=True)
class OAuthIdentity:
    provider: str
    subject: str
    email: str | None = None
    display_name: str | None = None


@dataclass(frozen=True)
class OAuthProviderConfig:
    provider: str
    client_id: str
    authorization_endpoint: str
    token_endpoint: str
    issuer: str
    jwks_uri: str
    scopes: str = "openid email profile"


class OAuthError(IdentityError):
    """Compatibility error for legacy OAuth callers."""


class OAuthService:
    @staticmethod
    def normalize_provider(provider: str) -> str:
        try:
            return identity_config.normalize_provider(provider)
        except ValueError as exc:
            raise ValueError("unsupported_oauth_provider") from exc

    @staticmethod
    def code_challenge(verifier: str) -> str:
        return build_code_challenge(verifier)

    @staticmethod
    def verify_state(*, expected: str, actual: str) -> None:
        if not expected or not actual or expected != actual:
            raise OAuthError("oauth_state_mismatch")

    @staticmethod
    def default_config(provider: str, client_id: str) -> OAuthProviderConfig:
        provider = OAuthService.normalize_provider(provider)
        if not client_id:
            raise ValueError("oauth_client_id_required")
        if provider == "google":
            cfg = identity_config.GoogleOAuthConfig(client_id=client_id)
            return OAuthProviderConfig(
                provider=provider,
                client_id=client_id,
                authorization_endpoint=cfg.authorization_endpoint,
                token_endpoint=cfg.token_endpoint,
                issuer=cfg.issuer,
                jwks_uri=cfg.jwks_uri,
                scopes=cfg.scopes,
            )
        return OAuthProviderConfig(
            provider=provider,
            client_id=client_id,
            authorization_endpoint="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            token_endpoint="https://login.microsoftonline.com/common/oauth2/v2.0/token",
            issuer="https://login.microsoftonline.com/common/v2.0",
            jwks_uri="https://login.microsoftonline.com/common/discovery/v2.0/keys",
        )

    @staticmethod
    def validate_id_token(
        token: str,
        *,
        config: OAuthProviderConfig,
        nonce: str | None = None,
    ) -> dict:
        issuer = (
            (config.issuer, "accounts.google.com")
            if config.provider == "google"
            else config.issuer
        )
        try:
            return validate_oidc_id_token(
                token,
                audience=config.client_id,
                issuer=issuer,
                nonce=nonce,
                verify_signature=False,
            )
        except IdentityStateMismatch as exc:
            raise OAuthError(str(exc)) from exc
        except IdentityTokenInvalid as exc:
            raise OAuthError(str(exc)) from exc

    @staticmethod
    def identity_from_claims(provider: str, claims: dict) -> OAuthIdentity:
        provider = OAuthService.normalize_provider(provider)
        subject = str(claims.get("sub") or "")
        if not subject:
            raise OAuthError("oauth_subject_missing")
        return OAuthIdentity(
            provider=provider,
            subject=subject,
            email=claims.get("email"),
            display_name=claims.get("name") or claims.get("preferred_username"),
        )

    @staticmethod
    def oauth_enabled(provider: str | None = None) -> bool:
        if provider is None:
            return os.environ.get("WORKLOGGER_IDENTITY_ENABLED", "1").lower() not in {
                "0",
                "false",
                "no",
                "off",
            }
        try:
            return identity_config.provider_available(provider)
        except Exception:
            return False

    @staticmethod
    def provider_from_environment(provider: str) -> OAuthProviderConfig | None:
        try:
            provider = OAuthService.normalize_provider(provider)
        except ValueError:
            return None
        if provider == "google":
            cfg = identity_config.google_oauth_config()
            if cfg is None:
                return None
            return OAuthService.default_config("google", cfg.client_id)
        return None

    def authenticate(self, provider: str, config: OAuthProviderConfig | None = None) -> ExternalIdentity:
        raise OAuthError("oauth_compat_authenticate_removed")
