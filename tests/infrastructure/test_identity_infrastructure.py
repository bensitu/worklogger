from __future__ import annotations

import os
import json
import time
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
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
    profile_from_oidc_token,
)
from worklogger.infrastructure.identity.pkce import build_code_challenge
from worklogger.infrastructure.identity.providers import DisabledIdentityProvider


class IdentityInfrastructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        public.update(kid="signing-key", use="sig", alg="RS256")
        cls.jwks = {"keys": [public]}

    def token(self, **overrides):
        claims = {"sub": "google-sub", "iss": "https://accounts.google.com", "aud": "client-id",
                  "exp": int(time.time()) + 300, "iat": int(time.time()), "nonce": "nonce",
                  "email": "person@example.test", "name": "Person"}
        claims.update(overrides)
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "signing-key"})

    def test_oidc_rejects_invalid_signatures_claims_and_nonce(self):
        for overrides in ({"iss": "https://other.example.com"}, {"aud": "other-client"},
                          {"exp": int(time.time()) - 1}, {"nonce": "other"}, {"sub": ""}):
            result = profile_from_oidc_token("google", self.token(**overrides), issuer="https://accounts.google.com",
                                            audience="client-id", jwks=self.jwks, expected_nonce="nonce")
            self.assertFalse(result.ok)
        self.assertFalse(profile_from_oidc_token("google", self.token(), issuer="https://accounts.google.com",
                                                audience="client-id", jwks={"keys": []}, expected_nonce="nonce").ok)
        self.assertFalse(profile_from_oidc_token("google", self.token(), issuer="https://accounts.google.com",
                                                audience="client-id", jwks=self.jwks, expected_nonce="").ok)
    def test_provider_availability_uses_direct_google_registration(self) -> None:
        env = {
            "WORKLOGGER_IDENTITY_ENABLED": "1",
            "WORKLOGGER_GOOGLE_LOGIN_ENABLED": "1",
            "WORKLOGGER_GOOGLE_CLIENT_ID": "google-client",
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

        profile = profile_from_oidc_token(
            "google",
            self.token(), issuer="https://accounts.google.com", audience="client-id", jwks=self.jwks,
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
                "idToken": self.token(sub="firebase-id", iss="https://securetoken.google.com/project",
                                      aud="project", firebase={"sign_in_provider": "google.com"}),
                "refreshToken": "must-not-persist",
            }, project_id="project", jwks=self.jwks,
        )
        self.assertTrue(firebase.ok)
        assert firebase.value is not None
        self.assertEqual(firebase.value.subject, "firebase-id")
        self.assertFalse(hasattr(firebase.value, "refresh_token"))
        self.assertFalse(profile_from_firebase_google_response({"localId": "forged", "idToken": "forged"},
                                                               project_id="project", jwks=self.jwks).ok)


if __name__ == "__main__":
    unittest.main()
