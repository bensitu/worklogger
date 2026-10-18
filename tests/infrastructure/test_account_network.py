"""Account routing, explicit remote consent, and authenticated proxy boundaries."""

import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.request import Request

from worklogger.app.ports import AIRequest
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.ai.account import AccountAIGateway
from worklogger.infrastructure.ai.generation_options import ExternalGenerationOptions, ExternalModelProfile
from worklogger.infrastructure.network import AccountHTTPTransport
from worklogger.infrastructure.http import _ExplicitProxyHandler, _PublicHTTPSConnection
from worklogger.infrastructure.update import GitHubReleaseUpdateChecker


class AccountNetworkTests(unittest.TestCase):
    def test_public_connections_resolve_once_and_connect_only_to_validated_addresses(self):
        import socket
        from worklogger.infrastructure.http import _connect_public, validate_https_url
        for url in ("https://0x7f.0.0.1", "https://0x7f.0x0.0x0.0x1"):
            with self.assertRaises(ValueError):
                validate_https_url(url, public_only=True)
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        with patch("socket.getaddrinfo", return_value=addresses) as resolve, patch("socket.create_connection") as connect:
            _connect_public(("example.com", 443), 5)
            resolve.assert_called_once()
            connect.assert_called_once_with(("93.184.216.34", 443), 5, None)
        addresses.append((socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)))
        with patch("socket.getaddrinfo", return_value=addresses), patch("socket.create_connection") as connect:
            with self.assertRaises(OSError):
                _connect_public(("example.com", 443), 5)
            connect.assert_not_called()

    def test_runtime_reads_do_not_load_unrelated_drafts_or_avatar_values(self):
        self.values.update(ai_assist_enabled="1", daily_note_draft="private draft", profile_avatar_png="private image")
        gateway = AccountAIGateway(local=Mock(available=True), settings=self.settings,
                                   user_id=1, key_store=self.keys, transport=self.transport)
        self.assertTrue(gateway.available)
        self.assertIsNone(self.transport.proxy_url())
        self.settings.get_all.assert_not_called()
        for call in self.settings.get_many.call_args_list:
            self.assertNotIn("daily_note_draft", call.args[1])
            self.assertNotIn("profile_avatar_png", call.args[1])

    def setUp(self):
        self.values = {}
        self.settings = Mock()
        self.settings.get_all.side_effect = lambda _user: dict(self.values)
        self.settings.get_many.side_effect = lambda _user, keys: {key: self.values[key] for key in keys if key in self.values}
        self.keys = Mock()
        self.keys.get_secret.return_value = Result.success("synthetic-api-key")
        self.password = Mock()
        self.password.load.return_value = Result.success("synthetic:password")
        self.requests = []
        self.routes = []
        def factory(**route):
            self.routes.append(route)
            def open_request(request, **options):
                self.requests.append(request)
                response = {"choices": [{"message": {"content": "Revised text"}}]} if request.data else {"tag_name": "v4.1.0"}
                return io.BytesIO(json.dumps(response).encode())
            return open_request
        self.transport = AccountHTTPTransport(settings=self.settings, user_id=1, proxy_password=self.password, opener_factory=factory)

    def test_remote_processing_is_explicit_and_never_a_local_failure_fallback(self):
        local = Mock(available=False)
        local.generate.return_value = Result.failure(SimpleNamespace(code="local_model_not_selected"))
        gateway = AccountAIGateway(local=local, settings=self.settings, user_id=1, key_store=self.keys, transport=self.transport)
        request = AIRequest(messages=({"role": "user", "content": "Synthetic text"},), model="default", timeout_seconds=30)
        gateway.generate(request)
        self.assertEqual(self.requests, [])
        self.keys.get_secret.assert_not_called()
        self.values.update(external_model_enabled="1", external_model_base_url="https://example.com/v1", external_model_name="configured-model")
        gateway.update_configuration(SimpleNamespace(external_api_key="synthetic-api-key", external_api_key_available=True))
        self.assertTrue(gateway.available)
        result = gateway.generate(request)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.value.text, "Revised text")
        payload = json.loads(self.requests[0].data)
        self.assertEqual(payload["model"], "configured-model")
        self.assertEqual(self.routes[-1], dict(public_only=False, allow_redirects=False, proxy_url=None))
        self.values["ai_assist_enabled"] = "0"
        self.assertFalse(gateway.available)
        self.assertFalse(gateway.generate(request).ok)
        self.assertEqual(len(self.requests), 1)

    def test_account_proxy_routes_updates_and_applies_live_configuration(self):
        checker = GitHubReleaseUpdateChecker(api_url="https://example.com/releases", opener=self.transport.opener(public_only=True))
        self.assertEqual(checker.check_latest_version("4.0.0").value, "4.1.0")
        self.password.load.assert_not_called()
        self.values.update(network_proxy_enabled="1", network_proxy_address="127.0.0.1", network_proxy_port="8080",
                           network_proxy_username="user", network_proxy_domain="organization")
        self.assertTrue(checker.check_latest_version("4.0.0").ok)
        self.assertEqual(self.routes[-1]["proxy_url"], "http://organization%5Cuser:synthetic%3Apassword@127.0.0.1:8080")
        self.assertTrue(self.routes[-1]["public_only"])
        self.values["network_proxy_enabled"] = "0"
        checker.check_latest_version("4.0.0")
        self.assertIsNone(self.routes[-1]["proxy_url"])
        self.values.update(network_proxy_enabled="1", network_proxy_address="https://proxy.example.com")
        result = checker.check_latest_version("4.0.0")
        self.assertFalse(result.ok)
        self.assertNotIn("synthetic", str(result.error))

    def test_external_generation_options_match_only_the_configured_endpoint_and_model(self):
        local = Mock(available=True)
        options = ExternalGenerationOptions(max_output_tokens=4096, token_limit_parameter="max_completion_tokens")
        gateway = AccountAIGateway(local=local, settings=self.settings, user_id=1, key_store=self.keys,
                                   transport=self.transport, model_profiles=(
                                       ExternalModelProfile("https://example.com/v1/", "configured-model", options),))
        request = AIRequest(({"role": "user", "content": "Full instructions"},), "default", 30,
                            local_messages=({"role": "user", "content": "Compact instructions"},))
        self.values.update(external_model_enabled="1", external_model_base_url="https://example.com/v1",
                           external_model_name="configured-model")
        self.assertTrue(gateway.generate(request).ok)
        payload = json.loads(self.requests[-1].data)
        self.assertEqual(payload["messages"], list(request.messages))
        self.assertEqual(payload["max_completion_tokens"], 4096)
        self.assertNotIn("max_tokens", payload)
        self.assertNotIn("temperature", payload)
        for key, value in (("external_model_name", "other-model"),
                           ("external_model_base_url", "https://other.example.com/v1")):
            previous = self.values[key]
            self.values[key] = value
            self.assertTrue(gateway.generate(request).ok)
            payload = json.loads(self.requests[-1].data)
            self.assertNotIn("max_completion_tokens", payload)
            self.assertNotIn("temperature", payload)
            self.values[key] = previous
        self.values["external_model_enabled"] = "0"
        gateway.generate(request)
        local.generate.assert_called_once_with(request)

    def test_explicit_proxy_ignores_environment_bypass_but_rejects_private_destinations(self):
        request = Request("https://example.com/file")
        with patch.dict("os.environ", {"NO_PROXY": "*"}):
            _ExplicitProxyHandler({"https": "http://proxy.example.com:8080"}).proxy_open(request, "http://proxy.example.com:8080", "https")
        self.assertEqual(request.host, "proxy.example.com:8080")
        self.assertEqual(request._tunnel_host, "example.com")
        connection = _PublicHTTPSConnection("127.0.0.1", 8080)
        connection.set_tunnel("example.com", 443)
        addresses = [(2, 1, 6, "", ("127.0.0.1", 443))]
        with patch("socket.getaddrinfo", return_value=addresses), patch("http.client.HTTPSConnection.connect") as connect:
            with self.assertRaises(OSError):
                connection.connect()
            connect.assert_not_called()

    def test_runtime_boolean_preferences_match_the_settings_decoder(self):
        local = Mock(available=True)
        gateway = AccountAIGateway(local=local, settings=self.settings, user_id=1, key_store=self.keys, transport=self.transport)
        for enabled in ("1", "true", "yes", " on "):
            self.values.update(ai_assist_enabled=enabled, network_proxy_enabled=enabled,
                               network_proxy_address="127.0.0.1", network_proxy_port="8080")
            self.assertTrue(gateway.available)
            self.assertEqual(self.transport.proxy_url(), "http://127.0.0.1:8080")
        for disabled in ("0", "false", "off"):
            self.values.update(ai_assist_enabled=disabled, network_proxy_enabled=disabled)
            self.assertFalse(gateway.available)
            self.assertIsNone(self.transport.proxy_url())
