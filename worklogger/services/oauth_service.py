"""OAuth/OIDC sign-in support for desktop Authorization Code + PKCE."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

_log = logging.getLogger(__name__)

OAUTH_PROVIDERS = {"google", "microsoft"}
OAUTH_SCOPES = "openid email profile"

GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_ISSUER = "https://accounts.google.com"
MICROSOFT_AUTHORIZATION_ENDPOINT = (
    "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
)
MICROSOFT_TOKEN_ENDPOINT = (
    "https://login.microsoftonline.com/common/oauth2/v2.0/token"
)
MICROSOFT_ISSUER = "https://login.microsoftonline.com/common/v2.0"
GOOGLE_JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
MICROSOFT_JWKS_URI = "https://login.microsoftonline.com/common/discovery/v2.0/keys"


@dataclass(frozen=True)
class OAuthIdentity:
    provider: str
    subject: str
    email: str | None
    display_name: str | None


@dataclass(frozen=True)
class OAuthProviderConfig:
    provider: str
    client_id: str
    authorization_endpoint: str
    token_endpoint: str
    issuer: str
    jwks_uri: str = ""
    scopes: str = OAUTH_SCOPES


class OAuthError(RuntimeError):
    """Raised when OAuth sign-in cannot complete safely."""


class OAuthService:
    """Run OAuth Authorization Code Flow with PKCE in the system browser."""

    @staticmethod
    def normalize_provider(provider: str) -> str:
        provider = str(provider or "").strip().lower()
        if provider not in OAUTH_PROVIDERS:
            raise ValueError("unsupported_oauth_provider")
        return provider

    @staticmethod
    def generate_code_verifier() -> str:
        return secrets.token_urlsafe(64)[:128]

    @staticmethod
    def code_challenge(verifier: str) -> str:
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    @staticmethod
    def generate_state() -> str:
        return secrets.token_urlsafe(32)

    @staticmethod
    def provider_from_environment(provider: str) -> OAuthProviderConfig | None:
        provider = OAuthService.normalize_provider(provider)
        if not OAuthService.oauth_enabled(provider):
            return None
        client_id = OAuthService._env(
            f"WORKLOGGER_{provider.upper()}_CLIENT_ID",
            f"{provider.upper()}_CLIENT_ID",
        )
        if not client_id:
            return None
        return OAuthService.default_config(provider, client_id)

    @staticmethod
    def oauth_enabled(provider: str | None = None) -> bool:
        global_enabled = OAuthService._env_bool(
            "WORKLOGGER_OAUTH_LOGIN_ENABLED",
            "OAUTH_LOGIN_ENABLED",
            default=True,
        )
        if not global_enabled:
            return False
        if provider is None:
            return True
        provider = OAuthService.normalize_provider(provider)
        return OAuthService._env_bool(
            f"WORKLOGGER_{provider.upper()}_LOGIN_ENABLED",
            f"{provider.upper()}_LOGIN_ENABLED",
            default=True,
        )

    @staticmethod
    def default_config(provider: str, client_id: str) -> OAuthProviderConfig:
        provider = OAuthService.normalize_provider(provider)
        if not client_id or not str(client_id).strip():
            raise ValueError("oauth_client_id_required")
        if provider == "google":
            return OAuthProviderConfig(
                provider=provider,
                client_id=client_id.strip(),
                authorization_endpoint=GOOGLE_AUTHORIZATION_ENDPOINT,
                token_endpoint=GOOGLE_TOKEN_ENDPOINT,
                issuer=GOOGLE_ISSUER,
                jwks_uri=GOOGLE_JWKS_URI,
            )
        return OAuthProviderConfig(
            provider=provider,
            client_id=client_id.strip(),
            authorization_endpoint=MICROSOFT_AUTHORIZATION_ENDPOINT,
            token_endpoint=MICROSOFT_TOKEN_ENDPOINT,
            issuer=MICROSOFT_ISSUER,
            jwks_uri=MICROSOFT_JWKS_URI,
        )

    @staticmethod
    def build_authorization_url(
        config: OAuthProviderConfig,
        *,
        redirect_uri: str,
        state: str,
        code_challenge: str,
        nonce: str,
    ) -> str:
        params = {
            "client_id": config.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": config.scopes,
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return config.authorization_endpoint + "?" + urllib.parse.urlencode(params)

    def authenticate(
        self,
        provider: str,
        *,
        timeout_seconds: int = 120,
        config: OAuthProviderConfig | None = None,
    ) -> OAuthIdentity:
        config = config or self.provider_from_environment(provider)
        if config is None:
            raise OAuthError("oauth_provider_not_configured")
        verifier = self.generate_code_verifier()
        challenge = self.code_challenge(verifier)
        state = self.generate_state()
        nonce = self.generate_state()
        callback = _OAuthCallbackServer(timeout_seconds=timeout_seconds)
        try:
            redirect_uri = callback.redirect_uri
            url = self.build_authorization_url(
                config,
                redirect_uri=redirect_uri,
                state=state,
                code_challenge=challenge,
                nonce=nonce,
            )
            _log.info("Opening OAuth browser flow for provider=%s", config.provider)
            if not webbrowser.open(url):
                raise OAuthError("oauth_browser_open_failed")
            result = callback.wait()
            if result.get("error"):
                raise OAuthError("oauth_provider_error")
            code = result.get("code")
            returned_state = result.get("state")
            self.verify_state(expected=state, actual=returned_state)
            if not code:
                raise OAuthError("oauth_authorization_code_missing")
            token_response = self.exchange_code_for_tokens(
                config,
                code=str(code),
                code_verifier=verifier,
                redirect_uri=redirect_uri,
            )
            claims = self.validate_id_token(
                str(token_response.get("id_token") or ""),
                config=config,
                nonce=nonce,
            )
            return self.identity_from_claims(config.provider, claims)
        finally:
            callback.close()

    @staticmethod
    def verify_state(*, expected: str, actual: str | None) -> None:
        if not actual or not secrets.compare_digest(str(expected), str(actual)):
            raise OAuthError("oauth_state_mismatch")

    @staticmethod
    def exchange_code_for_tokens(
        config: OAuthProviderConfig,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> dict[str, Any]:
        body = urllib.parse.urlencode({
            "client_id": config.client_id,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        }).encode("utf-8")
        req = urllib.request.Request(
            config.token_endpoint,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read(1024 * 1024)
        except urllib.error.URLError as exc:
            raise OAuthError("oauth_token_exchange_failed") from exc
        data = json.loads(raw.decode("utf-8"))
        if "id_token" not in data:
            raise OAuthError("oauth_id_token_missing")
        return data

    @staticmethod
    def validate_id_token(
        id_token: str,
        *,
        config: OAuthProviderConfig,
        nonce: str,
        now: int | None = None,
    ) -> dict[str, Any]:
        header = OAuthService._decode_jwt_header(id_token)
        if header.get("alg") != "none":
            OAuthService._verify_id_token_signature(id_token, config, header)
        claims = OAuthService._decode_jwt_claims(id_token)
        if not claims.get("sub"):
            raise OAuthError("oauth_subject_missing")
        audience = claims.get("aud")
        if isinstance(audience, list):
            audience_ok = config.client_id in audience
        else:
            audience_ok = audience == config.client_id
        if not audience_ok:
            raise OAuthError("oauth_audience_mismatch")
        issuer = str(claims.get("iss") or "").rstrip("/")
        expected_issuer = config.issuer.rstrip("/")
        if config.provider == "microsoft":
            if not issuer.startswith("https://login.microsoftonline.com/") or not issuer.endswith("/v2.0"):
                raise OAuthError("oauth_issuer_mismatch")
        elif issuer != expected_issuer:
            raise OAuthError("oauth_issuer_mismatch")
        if claims.get("nonce") != nonce:
            raise OAuthError("oauth_nonce_mismatch")
        exp = int(claims.get("exp") or 0)
        if exp and (now if now is not None else int(time.time())) >= exp:
            raise OAuthError("oauth_id_token_expired")
        return claims

    @staticmethod
    def identity_from_claims(provider: str, claims: dict[str, Any]) -> OAuthIdentity:
        provider = OAuthService.normalize_provider(provider)
        subject = str(claims.get("sub") or "").strip()
        if not subject:
            raise OAuthError("oauth_subject_missing")
        email = claims.get("email") or claims.get("preferred_username")
        name = claims.get("name") or claims.get("given_name")
        return OAuthIdentity(
            provider=provider,
            subject=subject,
            email=str(email).strip() if email else None,
            display_name=str(name).strip() if name else None,
        )

    @staticmethod
    def _decode_jwt_claims(id_token: str) -> dict[str, Any]:
        parts = str(id_token or "").split(".")
        if len(parts) < 2:
            raise OAuthError("oauth_id_token_invalid")
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)
        try:
            raw = base64.urlsafe_b64decode(payload.encode("ascii"))
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise OAuthError("oauth_id_token_invalid") from exc
        if not isinstance(data, dict):
            raise OAuthError("oauth_id_token_invalid")
        return data

    @staticmethod
    def _decode_jwt_header(id_token: str) -> dict[str, Any]:
        parts = str(id_token or "").split(".")
        if len(parts) < 2:
            raise OAuthError("oauth_id_token_invalid")
        header = parts[0]
        header += "=" * (-len(header) % 4)
        try:
            raw = base64.urlsafe_b64decode(header.encode("ascii"))
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise OAuthError("oauth_id_token_invalid") from exc
        if not isinstance(data, dict):
            raise OAuthError("oauth_id_token_invalid")
        return data

    @staticmethod
    def _verify_id_token_signature(
        id_token: str,
        config: OAuthProviderConfig,
        header: dict[str, Any],
    ) -> None:
        try:
            import jwt
        except ImportError as exc:
            raise OAuthError("oauth_jwt_dependency_missing") from exc
        kid = header.get("kid")
        alg = header.get("alg")
        if not kid or not alg:
            raise OAuthError("oauth_id_token_invalid")
        key_data = OAuthService._find_jwks_key(config.jwks_uri, str(kid))
        if key_data is None:
            raise OAuthError("oauth_jwks_key_missing")
        try:
            public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key_data))
            jwt.decode(
                id_token,
                key=public_key,
                algorithms=[str(alg)],
                options={
                    "verify_aud": False,
                    "verify_exp": False,
                    "verify_iss": False,
                },
            )
        except Exception as exc:
            raise OAuthError("oauth_id_token_signature_invalid") from exc

    @staticmethod
    def _find_jwks_key(jwks_uri: str, kid: str) -> dict[str, Any] | None:
        req = urllib.request.Request(
            jwks_uri,
            headers={"User-Agent": "WorkLogger OAuth"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read(1024 * 1024)
        except urllib.error.URLError as exc:
            raise OAuthError("oauth_jwks_fetch_failed") from exc
        data = json.loads(raw.decode("utf-8"))
        for key_data in data.get("keys", []):
            if key_data.get("kid") == kid:
                return key_data
        return None

    @staticmethod
    def _env(*names: str) -> str:
        for name in names:
            value = os.environ.get(name, "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _env_bool(*names: str, default: bool = False) -> bool:
        for name in names:
            raw = os.environ.get(name)
            if raw is None:
                continue
            return raw.strip().lower() in {"1", "true", "yes", "on"}
        return default


class _OAuthCallbackServer:
    def __init__(self, *, timeout_seconds: int):
        self._event = threading.Event()
        self._result: dict[str, str] = {}
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._make_handler())
        self._server.timeout = 1
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self._timeout_seconds = timeout_seconds

    @property
    def redirect_uri(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}/callback"

    def wait(self) -> dict[str, str]:
        if not self._event.wait(self._timeout_seconds):
            raise OAuthError("oauth_callback_timeout")
        return dict(self._result)

    def close(self) -> None:
        try:
            self._server.shutdown()
            self._server.server_close()
        except Exception:
            pass

    def _make_handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format, *args):
                return

            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path == "/callback" and not outer._event.is_set():
                    values = urllib.parse.parse_qs(parsed.query)
                    outer._result = {
                        key: value[0]
                        for key, value in values.items()
                        if value
                    }
                    outer._event.set()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h1>Sign-in completed</h1>"
                    b"<p>You can return to WorkLogger.</p></body></html>"
                )

        return Handler
