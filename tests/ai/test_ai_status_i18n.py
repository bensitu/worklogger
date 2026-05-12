import os
import sys
import unittest


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_ROOT = os.path.join(PROJECT_ROOT, "worklogger")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from utils.i18n import _, msg, set_language


class AIStatusI18nTests(unittest.TestCase):
    def test_ai_status_keys_are_localized_for_non_english_languages(self):
        keys = (
            "local_model_installing_deps",
            "local_model_downloading",
            "local_model_verifying",
            "local_model_hash_ok",
            "local_model_download_ok",
            "local_model_loading",
            "local_model_loaded",
            "local_model_generating",
            "ai_timeout_warning",
        )
        for lang in ("ja_JP", "ko_KR", "zh_CN", "zh_TW"):
            set_language(lang)
            for key in keys:
                text = msg(key)
                self.assertIsInstance(text, str)
                self.assertNotEqual(text, key, f"{key} was not localized in {lang}")

    def test_update_messages_are_localized_for_non_english_languages(self):
        checks = (
            "Check for Updates",
            "Checking for updates…",
            "You are on the latest version",
            "New version available: v{0}",
        )
        for lang in ("ja_JP", "ko_KR", "zh_CN", "zh_TW"):
            set_language(lang)
            for source in checks:
                text = _(source)
                self.assertIsInstance(text, str)
                self.assertNotEqual(text, source, f"{source} was not localized in {lang}")

    def test_missing_ai_provider_guidance_is_localized(self):
        source = (
            "Please enable a local model in Settings -> AI, or configure "
            "an external AI provider with API key, base URL, and model name."
        )
        for lang in ("ja_JP", "ko_KR", "zh_CN", "zh_TW"):
            set_language(lang)
            text = _(source)
            self.assertIsInstance(text, str)
            self.assertNotEqual(text, source, f"AI provider guidance was not localized in {lang}")


if __name__ == "__main__":
    unittest.main()

