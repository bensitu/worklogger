import os
import sys
import unittest


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_ROOT = os.path.join(PROJECT_ROOT, "worklogger")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from services.ai_assist_service import (
    AiAssistLaunchConfig,
    initial_user_message,
    system_prompt_for,
    target_output_language,
)


class _FakeServices:
    def __init__(self, lang: str):
        self._lang = lang

    def get_setting(self, key, default=None):
        return self._lang if key == "lang" else default


class AIPromptContractTests(unittest.TestCase):
    def test_target_language_uses_selected_app_language(self):
        self.assertEqual(target_output_language("ja_JP"), "日本語")

    def test_target_language_falls_back_to_services_setting(self):
        self.assertEqual(
            target_output_language("", _FakeServices("zh_CN")),
            "简体中文",
        )

    def test_period_system_prompts_are_scenario_specific_and_language_bound(self):
        cases = {
            "daily": "single day's work note",
            "weekly": "weekly work report",
            "monthly": "monthly work report",
            "analytics": "PDF-ready narrative",
        }
        for period_type, expected in cases.items():
            with self.subTest(period_type=period_type):
                prompt = system_prompt_for(period_type, "日本語")
                self.assertIn(expected, prompt)
                self.assertIn("日本語", prompt)
                self.assertIn("do not invent", prompt.lower())

    def test_initial_user_message_requires_selected_language_and_apply_ready_output(self):
        config = AiAssistLaunchConfig(
            period_type="monthly",
            period_label="May 2026",
            existing_text="draft",
            hint="make it concise",
        )
        message = initial_user_message(config, "context", "繁體中文")

        self.assertIn("## Target Output Language\n繁體中文", message)
        self.assertIn("## Existing Draft To Polish", message)
        self.assertIn("executive summary", message)
        self.assertIn("Return only the content to apply", message)
        self.assertNotIn("same language as the existing draft", message)


if __name__ == "__main__":
    unittest.main()

