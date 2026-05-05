import os
import sys
import unittest
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_ROOT = os.path.join(PROJECT_ROOT, "worklogger")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QLabel

from config.constants import LANGUAGE_FONT_FILES
from services.language_manager import LanguageManager
from utils.i18n import get_language


class LanguageManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._qt = QApplication.instance() or QApplication([])

    def test_language_font_assets_exist(self):
        font_dir = Path(APP_ROOT) / "assets" / "fonts"
        for filename in LANGUAGE_FONT_FILES.values():
            self.assertTrue((font_dir / filename).is_file(), filename)

    def test_apply_updates_gettext_language_and_qt_font(self):
        expected_families = {
            "en_US": "Noto Sans",
            "ja_JP": "Noto Sans CJK JP",
            "ko_KR": "Noto Sans CJK KR",
            "zh_CN": "Noto Sans CJK SC",
            "zh_TW": "Noto Sans CJK TC",
        }
        manager = LanguageManager()

        for lang, expected_family in expected_families.items():
            result = manager.apply(lang)
            self.assertEqual(result.language, lang)
            self.assertEqual(get_language(), lang)
            self.assertEqual(result.font_family, expected_family)
            self.assertIn(expected_family, QApplication.instance().font().family())
            self.assertTrue(result.font_path and Path(result.font_path).is_file())

    def test_apply_does_not_override_explicit_widget_font(self):
        label = QLabel("sample")
        label.setFont(QFont("monospace", 9))
        before_family = label.font().family()
        before_size = label.font().pointSize()

        LanguageManager().apply("ja_JP")

        self.assertEqual(label.font().family(), before_family)
        self.assertEqual(label.font().pointSize(), before_size)


if __name__ == "__main__":
    unittest.main()

