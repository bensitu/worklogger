"""Identity provider adapters."""

from __future__ import annotations

import json
import secrets
import webbrowser
from urllib.parse import urlencode
from urllib.request import Request
from urllib.error import HTTPError

from worklogger.domain.identity.models import ExternalIdentityProfile, IdentityProviderStatus
from worklogger.domain.shared.errors import InfrastructureError, AuthenticationError, CancellationError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.identity.config import (
    normalize_provider,
    provider_configured,
    IdentityConfigurationStore,
)
from worklogger.infrastructure.http import https_opener
from worklogger.infrastructure.identity.loopback import LoopbackAuthorization
from worklogger.infrastructure.identity.oidc import OidcAuthorizationBuilder, google_oidc_config, microsoft_oidc_config, profile_from_oidc_token
from worklogger.infrastructure.identity.pkce import generate_verifier


class BrowserIdentityProvider:
    """Authorization code flow with PKCE; provider tokens are never persisted."""

    def __init__(self, provider_id, display_name, *, configuration=None, browser_open=None, opener=None, timeout=180):
        self.provider_id = normalize_provider(provider_id)
        self.display_name = display_name
        self._configuration = configuration or IdentityConfigurationStore()
        self._browser_open = browser_open or webbrowser.open
        self._open = opener or https_opener(public_only=True, allow_redirects=False)
        self._timeout = timeout

    def status(self):
        loaded = self._configuration.load(self.provider_id)
        configured = bool(loaded.ok and loaded.value[0].client_id)
        available = bool(configured and loaded.value[1])
        message = "" if available else ("identity_provider_not_configured" if loaded.ok else "identity_configuration_invalid")
        return IdentityProviderStatus(self.provider_id, self.display_name, available, configured, message)

    def authenticate(self, *, cancellation=None):
        if not self.status().available:
            return Result.failure(InfrastructureError("identity_provider_not_configured", "identity_provider_not_configured"))
        try:
            registration, enabled = self._configuration.load(self.provider_id).value
            if not enabled or not registration.client_id:
                raise ValueError("identity_configuration_invalid")
            config = (google_oidc_config(registration.client_id) if self.provider_id == "google"
                      else microsoft_oidc_config(registration.client_id, registration.tenant_id))
            token_url = ("https://oauth2.googleapis.com/token" if self.provider_id == "google" else
                         f"https://login.microsoftonline.com/{registration.tenant_id}/oauth2/v2.0/token")
            keys_url = ("https://www.googleapis.com/oauth2/v3/certs" if self.provider_id == "google" else
                        f"https://login.microsoftonline.com/{registration.tenant_id}/discovery/v2.0/keys")
            state, nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), generate_verifier()
            host = "127.0.0.1" if self.provider_id == "google" else "localhost"
            with LoopbackAuthorization(state=state, hostname=host, timeout=self._timeout) as callback:
                url = OidcAuthorizationBuilder(config).authorization_url(redirect_uri=callback.redirect_uri,
                    state=state, nonce=nonce, code_verifier=verifier)
                if cancellation and cancellation.is_cancelled():
                    return _cancelled()
                if not url.ok or not self._browser_open(url.value):
                    return Result.failure(InfrastructureError("identity_browser_failed", "identity_browser_failed"))
                code = callback.wait(cancellation)
                if not code.ok:
                    return code
                if cancellation and cancellation.is_cancelled():
                    return _cancelled()
                fields = dict(client_id=registration.client_id, code=code.value,
                              redirect_uri=callback.redirect_uri, grant_type="authorization_code", code_verifier=verifier)
                if registration.client_secret:
                    fields["client_secret"] = registration.client_secret
                tokens = self._json(Request(token_url, data=urlencode(fields).encode("ascii"),
                    headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}))
            if cancellation and cancellation.is_cancelled():
                return _cancelled()
            token = tokens.get("id_token")
            if not isinstance(token, str) or not token:
                raise ValueError("identity_token_invalid")
            keys = self._json(Request(keys_url, headers={"Accept": "application/json"}))
            if cancellation and cancellation.is_cancelled():
                return _cancelled()
            return profile_from_oidc_token(self.provider_id, token, issuer=config.issuer,
                audience=registration.client_id, jwks=keys, expected_nonce=nonce)
        except HTTPError as exc:
            exc.close()
            return Result.failure(AuthenticationError("identity_token_exchange_failed", "identity_token_exchange_failed"))
        except (ValueError, TypeError, KeyError):
            return Result.failure(AuthenticationError("identity_auth_failed", "identity_auth_failed"))
        except Exception:
            return Result.failure(InfrastructureError("identity_network_failed", "identity_network_failed"))

    def _json(self, request):
        with self._open(request, timeout=15) as response:
            if response.getcode() != 200:
                raise ValueError("identity_response_invalid")
            data = response.read(262145)
        if len(data) > 262144:
            raise ValueError("identity_response_too_large")
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError("identity_response_invalid")
        return value


def _cancelled():
    return Result.failure(CancellationError("identity_authorization_cancelled", "identity_authorization_cancelled"))


class DisabledIdentityProvider:
    def __init__(
        self,
        provider_id: str,
        display_name: str,
        *,
        message: str = "identity_provider_not_configured",
    ) -> None:
        self.provider_id = normalize_provider(provider_id)
        self.display_name = display_name
        self._message = message

    def status(self) -> IdentityProviderStatus:
        configured = provider_configured(self.provider_id)
        return IdentityProviderStatus(
            provider=self.provider_id,
            display_name=self.display_name,
            available=False,
            configured=configured,
            message=self._message,
        )

    def authenticate(self) -> Result[ExternalIdentityProfile]:
        return Result.failure(InfrastructureError(self._message, self._message))
