"""OIDC provider helpers that avoid token persistence."""

from __future__ import annotations

from dataclasses import dataclass
import hmac
import jwt
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


def profile_from_oidc_token(
    provider: str,
    token: str,
    *,
    issuer: str,
    audience: str,
    jwks: Mapping[str, object],
    expected_nonce: str,
) -> Result[ExternalIdentityProfile]:
    verified = _verified_claims(token, issuer=issuer, audience=audience, jwks=jwks)
    if not verified.ok or verified.value is None:
        return Result.failure(verified.error)
    claims = verified.value
    nonce = claims.get("nonce")
    if not expected_nonce or not isinstance(nonce, str) or not hmac.compare_digest(nonce.encode(), expected_nonce.encode()):
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
    *,
    project_id: str,
    jwks: Mapping[str, object],
) -> Result[ExternalIdentityProfile]:
    verified = _verified_claims(str(response.get("idToken") or ""),
                                issuer=f"https://securetoken.google.com/{project_id}",
                                audience=project_id, jwks=jwks)
    if not verified.ok or verified.value is None:
        return Result.failure(verified.error)
    claims = verified.value
    subject = str(claims.get("sub") or "").strip()
    firebase = claims.get("firebase")
    if not subject or subject != response.get("localId") or not isinstance(firebase, dict) or firebase.get("sign_in_provider") != "google.com":
        return Result.failure(AuthenticationError("identity_subject_missing", "identity_subject_missing"))
    return Result.success(
        ExternalIdentityProfile(
            provider="google",
            subject=subject,
            email=_optional_str(claims.get("email")),
            display_name=_optional_str(claims.get("name")),
            issuer=str(claims["iss"]),
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


def microsoft_oidc_config(client_id: str, tenant_id: str) -> OidcProviderConfig:
    if not tenant_id or not all(char.isalnum() or char == "-" for char in tenant_id) or tenant_id.lower() in {"common", "organizations", "consumers"}:
        raise ValueError("identity_tenant_required")
    return OidcProviderConfig(
        provider="microsoft",
        client_id=client_id,
        authorization_endpoint=f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize",
        issuer=f"https://login.microsoftonline.com/{tenant_id}/v2.0",
    )


def _verified_claims(token: str, *, issuer: str, audience: str, jwks: Mapping[str, object]) -> Result[dict]:
    try:
        if not issuer or not audience or not token or len(token) > 32768:
            raise ValueError("identity_token_invalid")
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise ValueError("identity_token_invalid")
        keys = [key for key in jwt.PyJWKSet.from_dict(dict(jwks)).keys
                if key.key_id == header["kid"] and key.key_type == "RSA"
                and key.public_key_use in (None, "sig") and key.algorithm_name == "RS256"]
        if len(keys) != 1:
            raise ValueError("identity_signing_key_invalid")
        claims = jwt.decode(token, keys[0].key, algorithms=["RS256"], issuer=issuer, audience=audience,
                            options={"require": ["iss", "aud", "exp", "iat", "sub"]})
        authorized_party = claims.get("azp")
        if (authorized_party is not None and authorized_party != audience
                or isinstance(claims.get("aud"), list) and len(claims["aud"]) > 1 and authorized_party != audience):
            raise ValueError("identity_token_invalid")
        if not isinstance(claims.get("sub"), str) or not claims["sub"].strip():
            raise ValueError("identity_subject_missing")
        return Result.success(claims)
    except (jwt.PyJWTError, TypeError, ValueError, KeyError):
        return Result.failure(AuthenticationError("identity_token_invalid", "identity_token_invalid"))


def _optional_str(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None
