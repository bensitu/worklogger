import urllib.error
import json
import os
import ssl
import sys
import unittest
from unittest.mock import patch


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_ROOT = os.path.join(PROJECT_ROOT, "worklogger")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from services.app_services import AppServices
import services.report_service as report_service
from utils.i18n import get_translator


class _FakeResponse:
    def __init__(self, payload: dict | bytes):
        self._payload = payload

    def read(self, size=-1) -> bytes:
        if isinstance(self._payload, bytes):
            raw = self._payload
        else:
            raw = json.dumps(self._payload).encode("utf-8")
        if size is None or size < 0:
            return raw
        return raw[:size]

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False


class _FakeDB:
    pass


class UpdateVersionCompareTests(unittest.TestCase):
    def test_report_service_and_app_services_imports_succeed(self):
        self.assertTrue(callable(report_service.generate_weekly))
        self.assertTrue(AppServices)

    def test_semver_remote_greater(self):
        self.assertTrue(AppServices._is_remote_newer("2.0.0", "1.9.9"))

    def test_semver_remote_equal(self):
        self.assertFalse(AppServices._is_remote_newer("1.2.3", "1.2.3"))

    def test_semver_remote_lower(self):
        self.assertFalse(AppServices._is_remote_newer("1.2.2", "1.2.3"))

    def test_update_check_uses_semver_and_ignores_older_remote(self):
        svc = AppServices(db=_FakeDB(), current_user_id=1)

        with patch("services.app_services.APP_VERSION", "2.0.0"):
            with patch("urllib.request.urlopen", return_value=_FakeResponse({"tag_name": "v1.9.9"})):
                msg = svc._check_update_sync(lambda s: s)
        self.assertEqual(msg, "You are on the latest version")

    def test_update_check_reports_newer_remote(self):
        svc = AppServices(db=_FakeDB(), current_user_id=1)

        with patch("services.app_services.APP_VERSION", "1.9.9"):
            with patch("urllib.request.urlopen", return_value=_FakeResponse({"tag_name": "v2.0.0"})):
                msg = svc._check_update_sync(lambda s: s)
        self.assertEqual(msg, "New version available: v2.0.0")

    def test_update_check_messages_are_localized_without_header_artifacts(self):
        svc = AppServices(db=_FakeDB(), current_user_id=1)
        for lang in ("en_US", "zh_CN", "ja_JP"):
            tr = get_translator(lang).gettext
            with patch("services.app_services.APP_VERSION", "2.0.0"):
                with patch("urllib.request.urlopen", return_value=_FakeResponse({"tag_name": "v1.9.9"})):
                    text = svc._check_update_sync(tr)
            self.assertIsInstance(text, str)
            self.assertNotIn("Language:", text)
            self.assertNotIn("Content-Type: text/plain; charset=UTF-8", text)

    def test_update_check_retries_transient_url_error(self):
        svc = AppServices(db=_FakeDB(), current_user_id=1)
        calls = {"n": 0}

        def _urlopen(*_args, **_kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise urllib.error.URLError("temporary")
            return _FakeResponse({"tag_name": "v1.9.9"})

        with patch("services.app_services.APP_VERSION", "2.0.0"), \
             patch("urllib.request.urlopen", side_effect=_urlopen), \
             patch("services.app_services.time.sleep", return_value=None):
            msg = svc._check_update_sync(lambda s: s)

        self.assertEqual(msg, "You are on the latest version")
        self.assertEqual(calls["n"], 2)

    def test_update_check_rejects_oversized_response(self):
        svc = AppServices(db=_FakeDB(), current_user_id=1)
        with patch(
            "urllib.request.urlopen",
            return_value=_FakeResponse(b"{" + (b"x" * (512 * 1024 + 1))),
        ):
            msg = svc._check_update_sync(lambda s: s)
        self.assertIn("Could not check for updates", msg)
        self.assertNotIn("update_response_too_large", msg)

    def test_update_check_opens_circuit_after_repeated_failures(self):
        svc = AppServices(db=_FakeDB(), current_user_id=1)
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")), \
             patch("services.app_services.time.sleep", return_value=None):
            for _ in range(3):
                self.assertIn(
                    "Could not check for updates",
                    svc._check_update_sync(lambda s: s),
                )

        with patch("urllib.request.urlopen") as mocked:
            self.assertIn(
                "Could not check for updates",
                svc._check_update_sync(lambda s: s),
            )
        mocked.assert_not_called()

    def test_update_check_hides_raw_network_errors(self):
        cases = (
            ssl.SSLError("[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred"),
            urllib.error.URLError("proxy tunnel failed"),
            TimeoutError("timed out"),
            json.JSONDecodeError("bad json", "{", 0),
        )
        for exc in cases:
            svc = AppServices(db=_FakeDB(), current_user_id=1)
            with self.subTest(exc=type(exc).__name__), \
                 patch("urllib.request.urlopen", side_effect=exc), \
                 patch("services.app_services.time.sleep", return_value=None):
                msg = svc._check_update_sync(lambda s: s)

            self.assertIn("Could not check for updates", msg)
            self.assertIn("network connection", msg)
            self.assertNotIn("UNEXPECTED_EOF", msg)
            self.assertNotIn("proxy tunnel failed", msg)
            self.assertNotIn("bad json", msg)

    def test_no_hardcoded_japanese_latest_version_literal(self):
        target = "現在のバージョンは最新です"
        for root, _dirs, files in os.walk(APP_ROOT):
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(root, name)
                with open(path, "r", encoding="utf-8") as f:
                    text = f.read()
                self.assertNotIn(target, text, f"Found hardcoded Japanese literal in {path}")


if __name__ == "__main__":
    unittest.main()
