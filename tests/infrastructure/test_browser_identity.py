"""Browser authorization, callback isolation, token verification and registration storage."""

import io
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import tempfile
from threading import Thread
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from worklogger.app.job_runner import CancellationToken
from worklogger.infrastructure.identity.config import IdentityConfigurationStore, ProviderRegistration
from worklogger.infrastructure.identity.loopback import LoopbackAuthorization
from worklogger.infrastructure.identity.pkce import build_code_challenge
from worklogger.infrastructure.identity.providers import BrowserIdentityProvider
from worklogger.infrastructure.security.key_store import FileMachineKeyProvider, HmacSecretBox


class Response(io.BytesIO):
    def getcode(self):
        return 200


class BrowserIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        public.update(kid="signing-key", use="sig", alg="RS256")
        cls.keys = {"keys": [public]}

    def setUp(self):
        self.enterContext(patch.dict(os.environ, {}, clear=True))
        folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = IdentityConfigurationStore(folder / "identity.enc",
            secret_box=HmacSecretBox(FileMachineKeyProvider(folder / "machine.key")))

    def test_registration_storage_encrypts_values_and_respects_managed_overrides(self):
        registration = ProviderRegistration("client-id", client_secret="desktop-registration")
        self.assertTrue(self.store.save("google", registration).ok)
        self.assertEqual(self.store.load("google").value, (registration, True))
        self.assertNotIn("desktop-registration", self.store._path.read_text())
        self.assertNotIn("desktop-registration", repr(registration))
        with patch.dict(os.environ, {"WORKLOGGER_GOOGLE_CLIENT_ID": "managed-client"}):
            self.assertEqual(self.store.load("google").value[0].client_id, "managed-client")
            self.assertFalse(self.store.save("google", registration).ok)
        self.assertFalse(self.store.save("microsoft", ProviderRegistration("client", "common")).ok)

    def test_loopback_rejects_unbound_and_duplicate_callbacks_and_closes_listener(self):
        with LoopbackAuthorization(state="expected", timeout=0.02) as callback:
            self.assertEqual(callback.server.server_address[0], "127.0.0.1")
            for query, host in (("state=wrong&code=c", callback.authority),
                                ("state=expected&state=expected&code=c", callback.authority),
                                ("state=expected&code=c&error=denied", callback.authority),
                                ("state=expected&code=c", "attacker.example")):
                self.assertFalse(callback._accept("/callback?" + query, host))
            self.assertFalse(callback._accept("/wrong?state=expected&code=c", callback.authority))
            self.assertTrue(callback._accept("/callback?state=expected&code=c", callback.authority))
            self.assertFalse(callback._accept("/callback?state=expected&code=replay", callback.authority))
            self.assertEqual(callback.wait(None).value, "c")
        self.assertEqual(callback.server.socket.fileno(), -1)
        with LoopbackAuthorization(state="expected", timeout=0.01) as callback:
            self.assertEqual(callback.wait(None).error.code, "identity_authorization_timeout")
        token = CancellationToken()
        token.cancel()
        with LoopbackAuthorization(state="expected") as callback:
            self.assertEqual(callback.wait(token).error.code, "identity_authorization_cancelled")

    def _flow(self, provider, *, denied=False, claims_override=None, cancel_after_exchange=False):
        registration = ProviderRegistration("client-id", "tenant-id" if provider == "microsoft" else "")
        self.assertTrue(self.store.save(provider, registration).ok)
        authorization, requests, threads, responses = {}, [], [], []
        cancellation = CancellationToken()
        def browser(url):
            authorization.update({key: values[0] for key, values in parse_qs(urlsplit(url).query).items()})
            def respond():
                query = dict(state=authorization["state"])
                query["error" if denied else "code"] = "access_denied" if denied else "authorization-code"
                redirect = urlsplit(authorization["redirect_uri"])
                connection = HTTPConnection("127.0.0.1", redirect.port, timeout=3)
                try:
                    connection.request("GET", redirect.path + "?" + urlencode(query), headers={"Host": redirect.netloc})
                    reply = connection.getresponse()
                    responses.append(reply.read().decode())
                finally:
                    connection.close()
            thread = Thread(target=respond)
            thread.start()
            threads.append(thread)
            return True
        def transport(request, *, timeout):
            requests.append(request)
            if request.data:
                fields = {key: values[0] for key, values in parse_qs(request.data.decode()).items()}
                self.assertEqual(fields["redirect_uri"], authorization["redirect_uri"])
                self.assertEqual(build_code_challenge(fields["code_verifier"]), authorization["code_challenge"])
                self.assertEqual(fields["grant_type"], "authorization_code")
                self.assertNotIn("client_secret", fields)
                issuer = ("https://accounts.google.com" if provider == "google" else
                          "https://login.microsoftonline.com/tenant-id/v2.0")
                claims = dict(iss=issuer, aud="client-id", sub="provider-subject", nonce=authorization["nonce"],
                              exp=int(time.time()) + 300, iat=int(time.time()), name="Mary")
                claims.update(claims_override or {})
                token = jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "signing-key"})
                if cancel_after_exchange:
                    cancellation.cancel()
                return Response(json.dumps(dict(id_token=token, access_token="not-persisted")).encode())
            return Response(json.dumps(self.keys).encode())
        client = BrowserIdentityProvider(provider, provider.title(), configuration=self.store,
                                        browser_open=browser, opener=transport, timeout=3)
        result = client.authenticate(cancellation=cancellation)
        for thread in threads:
            thread.join(4)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(responses), 1)
        self.assertNotIn("authorization-code", responses[0])
        return result, requests

    def test_google_and_microsoft_authorization_verify_signed_profiles(self):
        for provider in ("google", "microsoft"):
            with self.subTest(provider=provider):
                result, requests = self._flow(provider)
                self.assertTrue(result.ok, result.error)
                self.assertEqual(result.value.subject, "provider-subject")
                self.assertEqual(result.value.display_name, "Mary")
                self.assertEqual(len(requests), 2)
                self.assertNotIn("not-persisted", self.store._path.read_text())

    def test_denied_cancelled_and_invalid_tokens_cannot_authenticate(self):
        result, requests = self._flow("google", denied=True)
        self.assertEqual(result.error.code, "identity_authorization_cancelled")
        self.assertEqual(requests, [])
        result, requests = self._flow("google", claims_override={"nonce": "wrong"})
        self.assertEqual(result.error.code, "identity_nonce_mismatch")
        result, requests = self._flow("google", cancel_after_exchange=True)
        self.assertEqual(result.error.code, "identity_authorization_cancelled")
        self.assertEqual(len(requests), 1)

    def test_browser_failure_and_unconfigured_clients_do_not_exchange_tokens(self):
        client = BrowserIdentityProvider("google", "Google", configuration=self.store, browser_open=lambda _url: False)
        self.assertFalse(client.status().available)
        self.assertEqual(client.authenticate().error.code, "identity_provider_not_configured")
        self.assertTrue(self.store.save("google", ProviderRegistration("client-id")).ok)
        self.assertTrue(client.status().available)
        self.assertEqual(client.authenticate().error.code, "identity_browser_failed")

