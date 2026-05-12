from __future__ import annotations

import urllib.parse

from ..config import FirebaseBrokerConfig
from ..errors import IdentityBrokerError
from ..http_client import post_json
from ..models import ExternalIdentity, IdentityAuthResult


class FirebaseIdentityBroker:
    endpoint = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithIdp"

    def sign_in_with_google_id_token(
        self,
        google_id_token: str,
        *,
        config: FirebaseBrokerConfig,
    ) -> IdentityAuthResult:
        if not google_id_token:
            raise IdentityBrokerError("identity_id_token_missing")
        url = self.endpoint + "?" + urllib.parse.urlencode({"key": config.api_key})
        data = post_json(
            url,
            {
                "postBody": urllib.parse.urlencode({
                    "id_token": google_id_token,
                    "providerId": "google.com",
                }),
                "requestUri": "http://localhost",
                "returnIdpCredential": True,
                "returnSecureToken": True,
            },
            error_cls=IdentityBrokerError,
        )
        local_id = str(data.get("localId") or "")
        if not local_id:
            raise IdentityBrokerError("identity_firebase_local_id_missing")
        issuer = (
            f"https://securetoken.google.com/{config.project_id}"
            if config.project_id
            else "firebase"
        )
        expires_in = data.get("expiresIn")
        try:
            expires_value = int(expires_in) if expires_in is not None else None
        except (TypeError, ValueError):
            expires_value = None
        return IdentityAuthResult(
            identity=ExternalIdentity(
                provider="google",
                broker="firebase",
                issuer=issuer,
                subject=local_id,
                email=data.get("email"),
                display_name=data.get("displayName"),
                avatar_url=data.get("photoUrl"),
                federated_subject=data.get("federatedId"),
                raw_provider=data.get("providerId") or "google.com",
            ),
            id_token=data.get("idToken"),
            refresh_token=data.get("refreshToken"),
            expires_in=expires_value,
        )
