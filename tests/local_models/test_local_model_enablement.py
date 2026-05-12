import os
import sys
from pathlib import Path
import unittest
from unittest.mock import patch


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_ROOT = os.path.join(PROJECT_ROOT, "worklogger")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from services.app_services import AppServices
from services.local_model_service import LOCAL_MODEL_SENTINEL, LocalModelService, should_use_local_model
from utils.i18n import LANG_NAMES, get_translator


class _FakeDB:
    def __init__(self, settings: dict[str, str]):
        self._settings = dict(settings)

    def get_setting(self, key, default=None, *, user_id=None):
        return self._settings.get(key, default)

    def set_setting(self, key, value, *, user_id=None):
        self._settings[key] = str(value)


class LocalModelEnablementTests(unittest.TestCase):
    def test_should_use_local_model_false_when_disabled(self):
        services = _FakeDB({"local_model_enabled": "0"})
        with patch("services.local_model_service.verify_model_file", return_value=True):
            self.assertFalse(should_use_local_model(services))

    def test_should_use_local_model_true_when_enabled_and_ready(self):
        services = _FakeDB({"local_model_enabled": "1"})
        with patch("services.local_model_service.verify_model_file", return_value=True):
            self.assertTrue(should_use_local_model(services))

    def test_resolve_ai_params_falls_back_to_cloud_when_local_disabled(self):
        svc = AppServices(db=_FakeDB({
            "local_model_enabled": "0",
            "ai_base_url": "https://api.example.com/v1",
            "ai_model": "gpt-test",
        }), current_user_id=1)
        svc.get_secret = lambda name: "cloud_key"  # type: ignore[method-assign]
        with patch("services.local_model_service.verify_model_file", return_value=True):
            key, url, model = svc.resolve_ai_params(secondary=False)
        self.assertEqual((key, url, model), ("cloud_key", "https://api.example.com/v1", "gpt-test"))

    def test_resolve_ai_params_uses_local_sentinel_when_enabled_and_ready(self):
        svc = AppServices(db=_FakeDB({"local_model_enabled": "1"}), current_user_id=1)
        with patch("services.local_model_service.verify_model_file", return_value=True):
            key, url, model = svc.resolve_ai_params(secondary=False)
        self.assertEqual((key, url, model), (LOCAL_MODEL_SENTINEL, "", ""))

    def test_load_provider_is_blocked_by_global_switch(self):
        services = _FakeDB({"local_model_enabled": "0"})
        svc = LocalModelService(models_dir=Path(PROJECT_ROOT) / "tests" / "_tmp_models_disabled")
        with self.assertRaises(RuntimeError) as ctx:
            svc.load_provider(services=services)
        self.assertEqual(str(ctx.exception), "ai_assist.local_model_not_running")

    def test_i18n_has_fallback_for_new_local_model_keys(self):
        for lang in LANG_NAMES:
            tr = get_translator(lang)
            self.assertIsInstance(
                tr.gettext("Show overnight indicator"),
                str,
            )
            self.assertIsInstance(
                tr.gettext("Local model is disabled."),
                str,
            )
            self.assertIsInstance(
                tr.gettext("Local model unavailable - using external model instead."),
                str,
            )


if __name__ == "__main__":
    unittest.main()

