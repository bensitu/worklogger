from __future__ import annotations

import webbrowser

from . import config as identity_config
from .brokers.firebase import FirebaseIdentityBroker
from .callback_server import LoopbackCallbackServer
from .errors import (
    IdentityBrokerError,
    IdentityCallbackTimeout,
    IdentityFlowCancelled,
    IdentityProviderNotConfigured,
    IdentityProviderUnavailable,
    IdentityStateMismatch,
)
from .models import ExternalIdentity
from .pkce import build_code_challenge, generate_code_verifier, generate_nonce, generate_state
from .providers.google import GoogleProvider


class ExternalIdentityService:
    def __init__(self, services=None):
        self._services = services

    def provider_configured(self, provider: str) -> bool:
        return identity_config.provider_configured(provider, self._services)

    def provider_available(self, provider: str) -> bool:
        return identity_config.provider_available(provider, self._services)

    def authenticate(
        self,
        provider: str,
        *,
        timeout_seconds: int = 120,
    ) -> ExternalIdentity:
        provider = identity_config.normalize_provider(provider)
        if provider == "google":
            return self.authenticate_google_firebase(timeout_seconds=timeout_seconds)
        raise IdentityProviderUnavailable("identity_provider_unavailable")

    def authenticate_google_firebase(
        self,
        *,
        timeout_seconds: int = 120,
    ) -> ExternalIdentity:
        if not self.provider_available("google"):
            if self.provider_configured("google"):
                raise IdentityProviderUnavailable("identity_provider_unavailable")
            raise IdentityProviderNotConfigured("identity_provider_not_configured")
        google_config = identity_config.google_oauth_config(self._services)
        firebase_config = identity_config.firebase_broker_config(self._services)
        if google_config is None or firebase_config is None:
            raise IdentityProviderNotConfigured("identity_provider_not_configured")

        verifier = generate_code_verifier()
        challenge = build_code_challenge(verifier)
        state = generate_state()
        nonce = generate_nonce()
        callback = LoopbackCallbackServer(timeout_seconds=timeout_seconds)
        redirect_uri = callback.redirect_uri
        try:
            provider = GoogleProvider(google_config)
            url = provider.build_authorization_url(
                redirect_uri=redirect_uri,
                state=state,
                nonce=nonce,
                code_challenge=challenge,
            )
            if not webbrowser.open(url, new=1, autoraise=True):
                raise IdentityProviderUnavailable("identity_browser_open_failed")
            params = callback.wait_for_callback()
        except IdentityCallbackTimeout:
            raise
        finally:
            callback.close()

        if params.get("error"):
            raise IdentityFlowCancelled(str(params.get("error") or "identity_flow_cancelled"))
        if params.get("state") != state:
            raise IdentityStateMismatch("identity_state_mismatch")
        code = str(params.get("code") or "")
        if not code:
            raise IdentityFlowCancelled("identity_authorization_code_missing")

        tokens = provider.exchange_code_for_tokens(
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=verifier,
        )
        claims = provider.validate_id_token(tokens.id_token, nonce=nonce)
        try:
            auth_result = FirebaseIdentityBroker().sign_in_with_google_id_token(
                tokens.id_token,
                config=firebase_config,
            )
            return auth_result.identity
        except IdentityBrokerError:
            return self._google_oidc_identity(claims)

    @staticmethod
    def _google_oidc_identity(claims: dict) -> ExternalIdentity:
        subject = str(claims.get("sub") or "").strip()
        if not subject:
            raise IdentityFlowCancelled("identity_subject_missing")
        return ExternalIdentity(
            provider="google",
            broker="direct_oidc",
            issuer=str(claims.get("iss") or "https://accounts.google.com"),
            subject=subject,
            email=claims.get("email"),
            display_name=claims.get("name"),
            avatar_url=claims.get("picture"),
            federated_subject=subject,
            raw_provider="google.com",
        )

    def authenticate_direct_oidc(
        self,
        provider: str,
        *,
        timeout_seconds: int = 120,
    ) -> ExternalIdentity:
        raise IdentityProviderUnavailable("identity_provider_unavailable")
