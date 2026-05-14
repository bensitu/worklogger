"""OIDC provider helpers that avoid token persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlencode

from worklogger.domain.identity.models import ExternalIdentityProfile
from worklogger.domain.shared.errors import AuthenticationError, ValidationError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.identity.pkce import build_code_challenge


@dataclass(frozen=True)
class OidcProviderConfig:
    provider: str
    client_id: str
    authorization_endpoint: str
    issuer: str
    scopes: str = "openid email profile"


class OidcAuthorizationBuilder:
    def __init__(self, config: OidcProviderConfig) -> None:
        self._config = config

    def authorization_url(
        self,
        *,
        redirect_uri: str,
        state: str,
        nonce: str,
        code_verifier: str,
    ) -> Result[str]:
        if not self._config.client_id:
            return Result.failure(ValidationError("identity_client_id_required", "identity_client_id_required"))
        if not redirect_uri or not state or not nonce or not code_verifier:
            return Result.failure(
                ValidationError(
                    "identity_oauth_parameter_required",
                    "identity_oauth_parameter_required",
                )
            )
        params = {
            "client_id": self._config.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": self._config.scopes,
            "state": state,
            "nonce": nonce,
            "code_challenge": build_code_challenge(code_verifier),
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
        return Result.success(f"{self._config.authorization_endpoint}?{urlencode(params)}")


def profile_from_oidc_claims(
    provider: str,
    claims: Mapping[str, object],
    *,
    expected_nonce: str | None = None,
) -> Result[ExternalIdentityProfile]:
    if expected_nonce is not None and str(claims.get("nonce") or "") != expected_nonce:
        return Result.failure(AuthenticationError("identity_nonce_mismatch", "identity_nonce_mismatch"))
    subject = str(claims.get("sub") or "").strip()
    if not subject:
        return Result.failure(AuthenticationError("identity_subject_missing", "identity_subject_missing"))
    return Result.success(
        ExternalIdentityProfile(
            provider=provider,
            subject=subject,
            email=_optional_str(claims.get("email")),
            display_name=_optional_str(claims.get("name")),
            issuer=_optional_str(claims.get("iss")) or "",
        )
    )


def profile_from_firebase_google_response(
    response: Mapping[str, object],
) -> Result[ExternalIdentityProfile]:
    subject = str(response.get("localId") or "").strip()
    if not subject:
        return Result.failure(AuthenticationError("identity_subject_missing", "identity_subject_missing"))
    return Result.success(
        ExternalIdentityProfile(
            provider="google",
            subject=subject,
            email=_optional_str(response.get("email")),
            display_name=_optional_str(response.get("displayName")),
            issuer="firebase",
            broker="firebase",
            federated_subject=_optional_str(response.get("federatedId")) or "",
            raw_provider=_optional_str(response.get("providerId")) or "",
        )
    )


def google_oidc_config(client_id: str) -> OidcProviderConfig:
    return OidcProviderConfig(
        provider="google",
        client_id=client_id,
        authorization_endpoint="https://accounts.google.com/o/oauth2/v2/auth",
        issuer="https://accounts.google.com",
    )


def microsoft_oidc_config(client_id: str) -> OidcProviderConfig:
    return OidcProviderConfig(
        provider="microsoft",
        client_id=client_id,
        authorization_endpoint="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        issuer="https://login.microsoftonline.com/common/v2.0",
    )


def _optional_str(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None
