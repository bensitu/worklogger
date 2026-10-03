from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QSettings

from worklogger.infrastructure.i18n import get_language, set_language
from worklogger.infrastructure.language_preferences import LanguagePreferences, initialize_language


class LanguagePreferencesTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "preferences.ini"
        self.addCleanup(set_language, "en_US")
        self.enterContext(patch.dict("os.environ", {"WORKLOGGER_LANG": ""}))

    def preferences(self):
        return LanguagePreferences(QSettings(str(self.path), QSettings.Format.IniFormat))

    def test_explicit_choice_persists_across_store_instances(self):
        self.assertIsNone(self.preferences().load())
        self.assertTrue(self.preferences().save("zh-Hant").ok)
        self.assertEqual(self.preferences().load(), "zh_TW")

    def test_first_launch_uses_system_language_without_persisting_detection(self):
        with patch("worklogger.infrastructure.language_preferences.detect_system_language", return_value="ja_JP"):
            self.assertEqual(initialize_language(self.preferences()), "ja_JP")
        self.assertEqual(get_language(), "ja_JP")
        self.assertIsNone(self.preferences().load())

    def test_manual_english_choice_overrides_non_english_system(self):
        self.assertTrue(self.preferences().save("en_US").ok)
        with patch("worklogger.infrastructure.language_preferences.detect_system_language") as detect:
            self.assertEqual(initialize_language(self.preferences()), "en_US")
        detect.assert_not_called()

    def test_environment_override_does_not_overwrite_saved_choice(self):
        self.preferences().save("ko_KR")
        with patch.dict("os.environ", {"WORKLOGGER_LANG": "zh-HK"}):
            self.assertEqual(initialize_language(self.preferences()), "zh_TW")
        self.assertEqual(self.preferences().load(), "ko_KR")

    def test_invalid_preference_falls_back_to_detection(self):
        for value in ("unknown", "", ["en_US"]):
            settings = QSettings(str(self.path), QSettings.Format.IniFormat)
            settings.setValue("ui/language", value)
            settings.sync()
            with patch("worklogger.infrastructure.language_preferences.detect_system_language", return_value="ko_KR"):
                self.assertEqual(initialize_language(self.preferences()), "ko_KR")

    def test_read_failure_falls_back_and_write_failure_returns_error(self):
        for status in (QSettings.Status.AccessError, QSettings.Status.FormatError):
            settings = Mock(spec=QSettings)
            settings.status.return_value = status
            preferences = LanguagePreferences(settings)
            with patch("worklogger.infrastructure.language_preferences.detect_system_language", return_value="en_US"):
                self.assertEqual(initialize_language(preferences), "en_US")
            result = preferences.save("ja_JP")
            self.assertFalse(result.ok)
            self.assertEqual(result.error.code, "settings_save_failed")

    def test_storage_exception_is_handled(self):
        settings = Mock(spec=QSettings)
        settings.sync.side_effect = OSError("unavailable")
        preferences = LanguagePreferences(settings)
        self.assertIsNone(preferences.load())
        self.assertFalse(preferences.save("ja_JP").ok)
