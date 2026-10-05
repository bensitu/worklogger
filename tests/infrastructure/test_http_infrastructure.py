import io
import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request

from worklogger.app.ports import AIRequest
from worklogger.infrastructure.ai.external import OpenAICompatibleGateway
from worklogger.infrastructure.http import _PublicHTTPSConnection, _ValidatedRedirect, validate_https_url
from worklogger.infrastructure.update import GitHubReleaseUpdateChecker


class HTTPInfrastructureTests(unittest.TestCase):
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
