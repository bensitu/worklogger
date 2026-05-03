from __future__ import annotations

import urllib.parse

from ..config import GoogleOAuthConfig
from ..errors import IdentityTokenExchangeFailed
from ..http_client import post_form
from ..models import OAuthTokens
from ..token_validation import validate_oidc_id_token


class GoogleProvider:
    provider_name = "google"

    def __init__(self, config: GoogleOAuthConfig):
        self.config = config

    def build_authorization_url(
        self,
        *,
        redirect_uri: str,
        state: str,
        nonce: str,
        code_challenge: str,
    ) -> str:
        params = {
            "client_id": self.config.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": self.config.scopes,
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "select_account",
        }
        return self.config.authorization_endpoint + "?" + urllib.parse.urlencode(params)

    def exchange_code_for_tokens(
        self,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> OAuthTokens:
        data = post_form(
            self.config.token_endpoint,
            {
                "client_id": self.config.client_id,
                "code": code,
                "code_verifier": code_verifier,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
            error_cls=IdentityTokenExchangeFailed,
        )
        id_token = str(data.get("id_token") or "")
        if not id_token:
            raise IdentityTokenExchangeFailed("identity_id_token_missing")
        expires_in = data.get("expires_in")
        try:
            expires_value = int(expires_in) if expires_in is not None else None
        except (TypeError, ValueError):
            expires_value = None
        return OAuthTokens(
            id_token=id_token,
            access_token=data.get("access_token"),
            refresh_token=data.get("refresh_token"),
            expires_in=expires_value,
        )

    def validate_id_token(self, id_token: str, *, nonce: str) -> dict:
        return validate_oidc_id_token(
            id_token,
            audience=self.config.client_id,
            issuer=(self.config.issuer, "accounts.google.com"),
            nonce=nonce,
            jwks_uri=self.config.jwks_uri,
            verify_signature=True,
        )
