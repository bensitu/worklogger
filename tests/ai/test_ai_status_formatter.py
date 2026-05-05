import os
import sys
import unittest


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_ROOT = os.path.join(PROJECT_ROOT, "worklogger")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from utils.ai_status_formatter import parse_status, render_status_text


class AIStatusFormatterTests(unittest.TestCase):
    def test_parse_json_status(self):
        key, kw = parse_status('{"key":"ai_status_done"}')
        self.assertEqual(key, "ai_status_done")
        self.assertEqual(kw, {})

    def test_parse_double_encoded_json_status(self):
        key, kw = parse_status('"{\\"key\\":\\"ai_status_build\\",\\"model\\":\\"GPT-5\\"}"')
        self.assertEqual(key, "ai_status_build")
        self.assertEqual(kw, {"model": "GPT-5"})

    def test_parse_english_fallback(self):
        key, kw = parse_status("Connecting to model GPT-5...")
        self.assertEqual(key, "ai_status_connect")
        self.assertEqual(kw, {"model": "GPT-5"})

    def test_render_status_text_localized(self):
        text = render_status_text('{"key":"ai_status_build","model":"GPT-5"}', {
            "ai_status_build": "正在为 {model} 准备请求..."
        })
        self.assertEqual(text, "正在为 GPT-5 准备请求...")

    def test_render_raw_text(self):
        text = render_status_text("plain text", {"ai_status_done": "完成。"})
        self.assertEqual(text, "plain text")


if __name__ == "__main__":
    unittest.main()

