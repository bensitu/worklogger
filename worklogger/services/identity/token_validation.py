from __future__ import annotations

import time
import base64
import json

try:
    import jwt
except ImportError:  # pragma: no cover - depends on optional runtime package.
    jwt = None

from .errors import IdentityTokenInvalid


def decode_jwt_header(token: str) -> dict:
    if jwt is not None:
        try:
            header = jwt.get_unverified_header(token)
        except Exception as exc:
            raise IdentityTokenInvalid("identity_id_token_invalid") from exc
    else:
        header = _decode_part(token, 0)
    if str(header.get("alg", "")).lower() == "none":
        raise IdentityTokenInvalid("identity_id_token_alg_none")
    return dict(header)


def decode_jwt_claims(token: str) -> dict:
    decode_jwt_header(token)
    if jwt is not None:
        try:
            return dict(jwt.decode(token, options={"verify_signature": False, "verify_aud": False}))
        except Exception as exc:
            raise IdentityTokenInvalid("identity_id_token_invalid") from exc
    return _decode_part(token, 1)


def validate_oidc_id_token(
    token: str,
    *,
    audience: str,
    issuer: str | tuple[str, ...],
    nonce: str | None = None,
    jwks_uri: str | None = None,
    verify_signature: bool = True,
) -> dict:
    header = decode_jwt_header(token)
    try:
        if verify_signature:
            if jwt is None:
                raise IdentityTokenInvalid("identity_jwt_dependency_missing")
            if not jwks_uri:
                raise IdentityTokenInvalid("identity_jwks_uri_required")
            key = fetch_jwks_key(token, jwks_uri)
            claims = jwt.decode(
                token,
                key=key,
                algorithms=[str(header.get("alg"))],
                audience=audience,
                issuer=issuer,
            )
        else:
            claims = decode_jwt_claims(token)
            _validate_claims(claims, audience=audience, issuer=issuer, nonce=nonce)
    except IdentityTokenInvalid:
        raise
    except Exception as exc:
        raise IdentityTokenInvalid("identity_id_token_invalid") from exc
    _validate_claims(claims, audience=audience, issuer=issuer, nonce=nonce)
    return dict(claims)


def fetch_jwks_key(token: str, jwks_uri: str):
    if jwt is None:
        raise IdentityTokenInvalid("identity_jwt_dependency_missing")
    try:
        return jwt.PyJWKClient(jwks_uri).get_signing_key_from_jwt(token).key
    except Exception as exc:
        raise IdentityTokenInvalid("identity_jwks_key_not_found") from exc


def verify_jwt_signature(token: str, *, jwks_uri: str, audience: str, issuer: str) -> dict:
    return validate_oidc_id_token(
        token,
        audience=audience,
        issuer=issuer,
        jwks_uri=jwks_uri,
        verify_signature=True,
    )


def _validate_claims(
    claims: dict,
    *,
    audience: str,
    issuer: str | tuple[str, ...],
    nonce: str | None,
) -> None:
    if not claims.get("sub"):
        raise IdentityTokenInvalid("identity_subject_missing")
    aud = claims.get("aud")
    if isinstance(aud, list):
        aud_ok = audience in aud
    else:
        aud_ok = aud == audience
    if not aud_ok:
        raise IdentityTokenInvalid("identity_audience_mismatch")
    allowed_issuers = (issuer,) if isinstance(issuer, str) else issuer
    if claims.get("iss") not in allowed_issuers:
        raise IdentityTokenInvalid("identity_issuer_mismatch")
    exp = claims.get("exp")
    try:
        if exp is None or int(exp) <= int(time.time()):
            raise IdentityTokenInvalid("identity_id_token_expired")
    except ValueError as exc:
        raise IdentityTokenInvalid("identity_id_token_expired") from exc
    if nonce is not None and claims.get("nonce") != nonce:
        raise IdentityTokenInvalid("identity_nonce_mismatch")


def _decode_part(token: str, index: int) -> dict:
    try:
        part = token.split(".")[index]
        padded = part + "=" * (-len(part) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise IdentityTokenInvalid("identity_id_token_invalid") from exc
