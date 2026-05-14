from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from worklogger.infrastructure.identity.config import (
    provider_available,
    provider_configured,
)
from worklogger.infrastructure.identity.oidc import (
    OidcAuthorizationBuilder,
    google_oidc_config,
    profile_from_firebase_google_response,
    profile_from_oidc_claims,
)
from worklogger.infrastructure.identity.pkce import build_code_challenge
from worklogger.infrastructure.identity.providers import DisabledIdentityProvider


class IdentityInfrastructureTests(unittest.TestCase):
    def test_provider_availability_requires_google_and_firebase_config(self) -> None:
        env = {
            "WORKLOGGER_IDENTITY_ENABLED": "1",
            "WORKLOGGER_GOOGLE_LOGIN_ENABLED": "1",
            "WORKLOGGER_GOOGLE_CLIENT_ID": "google-client",
            "WORKLOGGER_FIREBASE_API_KEY": "firebase-key",
        }
        with patch.dict(os.environ, env, clear=False):
            self.assertTrue(provider_configured("google"))
            self.assertTrue(provider_available("google"))
            self.assertFalse(provider_available("microsoft"))

    def test_pkce_code_challenge_matches_rfc_vector(self) -> None:
        verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        self.assertEqual(
            build_code_challenge(verifier),
            "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
        )

    def test_disabled_provider_reports_no_token_storage_auth_failure(self) -> None:
        provider = DisabledIdentityProvider("google", "Google")
        result = provider.authenticate()

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code if result.error else "", "identity_provider_not_configured")

    def test_oidc_url_and_profiles_do_not_expose_tokens(self) -> None:
        builder = OidcAuthorizationBuilder(google_oidc_config("client-id"))
        url = builder.authorization_url(
            redirect_uri="http://127.0.0.1:49152/callback",
            state="state",
            nonce="nonce",
            code_verifier="verifier",
        )
        self.assertTrue(url.ok)
        assert url.value is not None
        self.assertIn("code_challenge=", url.value)

        profile = profile_from_oidc_claims(
            "google",
            {
                "sub": "google-sub",
                "email": "person@example.test",
                "name": "Person",
                "nonce": "nonce",
            },
            expected_nonce="nonce",
        )
        self.assertTrue(profile.ok)
        assert profile.value is not None
        self.assertFalse(hasattr(profile.value, "id_token"))

        firebase = profile_from_firebase_google_response(
            {
                "localId": "firebase-id",
                "email": "person@example.test",
                "federatedId": "google-sub",
                "providerId": "google.com",
                "idToken": "must-not-persist",
                "refreshToken": "must-not-persist",
            }
        )
        self.assertTrue(firebase.ok)
        assert firebase.value is not None
        self.assertEqual(firebase.value.subject, "firebase-id")
        self.assertFalse(hasattr(firebase.value, "refresh_token"))


if __name__ == "__main__":
    unittest.main()
