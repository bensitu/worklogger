import io
import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request

from worklogger.app.ports import AIRequest
from worklogger.infrastructure.ai.external import OpenAICompatibleGateway
from worklogger.infrastructure.ai.generation_options import ExternalGenerationOptions
from worklogger.infrastructure.http import _PublicHTTPSConnection, _ValidatedRedirect, validate_https_url
from worklogger.infrastructure.update import GitHubReleaseUpdateChecker


class HTTPInfrastructureTests(unittest.TestCase):
    def test_external_payload_includes_only_explicit_generation_parameters(self):
        for options, expected in (
            (ExternalGenerationOptions(), {}),
            (ExternalGenerationOptions(temperature=0, max_output_tokens=512), {"temperature": 0, "max_tokens": 512}),
            (ExternalGenerationOptions(max_output_tokens=2048, token_limit_parameter="max_completion_tokens"),
             {"max_completion_tokens": 2048}),
        ):
            with self.subTest(options=options):
                opener = Mock(side_effect=lambda *args, **kwargs: io.BytesIO(
                    b'{"choices":[{"message":{"content":"Revised text"}}]}'))
                result = OpenAICompatibleGateway(api_key="synthetic", opener=opener,
                                                generation_options=options).generate(
                    AIRequest(({"role": "user", "content": "Source"},), "model", 30))
                self.assertTrue(result.ok, result.error)
                payload = json.loads(opener.call_args.args[0].data)
                self.assertEqual(payload, dict(model="model", messages=[{"role": "user", "content": "Source"}], **expected))

    def test_certificate_context_is_shared_without_caching_proxy_credentials(self):
        from worklogger.infrastructure.http import _certificate_context, https_opener
        import ssl

        _certificate_context.cache_clear()
        with patch("worklogger.infrastructure.http.ssl.create_default_context", wraps=ssl.create_default_context) as create:
            https_opener(proxy_url="http://first:synthetic@proxy.example:8080")
            https_opener(proxy_url="http://second:replacement@proxy.example:8080")
            self.assertEqual(create.call_count, 1)
        _certificate_context.cache_clear()

    def test_public_transport_validates_urls_redirects_and_connected_peers(self):
        for url in ("http://example.com", "https://user:secret@example.com", "https://127.0.0.1",
                    "https://localhost", "https://0x7f000001", "https://[::1]", "https://169.254.169.254"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_https_url(url, public_only=True)
        self.assertEqual(validate_https_url("https://example.com/file", public_only=True), "https://example.com/file")
        redirect = _ValidatedRedirect(allow=True, public_only=True)
        with self.assertRaises(ValueError):
            redirect.redirect_request(Request("https://example.com"), None, 302, "", {}, "https://192.168.1.1")
        with self.assertRaises(HTTPError):
            _ValidatedRedirect(allow=False, public_only=False).redirect_request(
                Request("https://example.com", data=b"private"), None, 307, "", {}, "https://other.example.com")
        connection = _PublicHTTPSConnection("example.com")
        connection.sock = Mock()
        connection.sock.getpeername.return_value = ("127.0.0.1", 443)
        with patch("http.client.HTTPSConnection.connect"), self.assertRaises(OSError):
            connection.connect()
        self.assertIsNone(connection.sock)

    def test_authenticated_requests_do_not_retry_http_errors_or_timeouts(self):
        for error in (HTTPError("https://example.com", 401, "private secret", {},
                                io.BytesIO(json.dumps({"error": {"code": "invalid_api_key", "message": "private"}}).encode())),
                      TimeoutError("private secret")):
            opener = Mock(side_effect=error)
            result = OpenAICompatibleGateway(api_key="credential", opener=opener, retries=3).generate(
                AIRequest(messages=({"role": "user", "content": "private"},), model="model", timeout_seconds=1))
            self.assertFalse(result.ok)
            self.assertEqual(opener.call_count, 1)
            self.assertNotIn("private", str(result.error.details))
            self.assertNotIn("credential", str(result.error.details))

    def test_update_responses_are_bounded_and_require_an_object(self):
        for payload in (b"[]", b"x" * 65):
            opener = Mock(return_value=io.BytesIO(payload))
            result = GitHubReleaseUpdateChecker(api_url="https://example.com", opener=opener,
                                                max_response_bytes=64).check_latest_version("4.0.0")
            self.assertFalse(result.ok)
        result = GitHubReleaseUpdateChecker(api_url="https://example.com", opener=lambda *a, **k: io.BytesIO(
            b'{"tag_name":"v4.1.0"}')).check_latest_version("4.0.0")
        self.assertEqual(result.value, "4.1.0")

    def test_updates_ignore_prereleases_and_recognize_their_final_release(self):
        for tag, flags, current, expected in (
            ("v4.1.0-beta.1", {}, "4.0.0", None),
            ("v4.1.0", {"prerelease": True}, "4.0.0", None),
            ("v4.1.0", {"draft": True}, "4.0.0", None),
            ("v4.1.0", {}, "4.1.0-beta.1", "4.1.0"),
            ("v4.1.0+build.2", {}, "4.1.0+build.1", None),
        ):
            with self.subTest(tag=tag, flags=flags):
                payload = json.dumps(dict(tag_name=tag, **flags)).encode()
                checker = GitHubReleaseUpdateChecker(api_url="https://example.com", opener=lambda *a, **k: io.BytesIO(payload))
                result = checker.check_latest_version(current)
                self.assertTrue(result.ok, result.error)
                self.assertEqual(result.value, expected)
