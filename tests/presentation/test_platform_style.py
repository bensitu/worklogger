"""Verify base-style compatibility without changing other platform styles."""

import unittest
from unittest.mock import Mock, patch

from worklogger.presentation.theme.platform_style import configure_application_style


class PlatformStyleTests(unittest.TestCase):
    def test_windows11_uses_fusion_and_repeated_calls_keep_the_style(self):
        application = Mock()
        application.style.return_value.objectName.side_effect = ("windows11", "fusion")
        with patch("worklogger.presentation.theme.platform_style.sys.platform", "win32"), \
             patch("worklogger.presentation.theme.platform_style.QApplication.instance", return_value=application):
            configure_application_style()
            configure_application_style()
        application.setStyle.assert_called_once_with("Fusion")
        application.setStyleSheet.assert_not_called()
        application.setFont.assert_not_called()

    def test_other_windows_styles_are_preserved(self):
        for name in ("fusion", "windows", "", "custom"):
            with self.subTest(style=name):
                application = Mock()
                application.style.return_value.objectName.return_value = name
                with patch("worklogger.presentation.theme.platform_style.sys.platform", "win32"), \
                     patch("worklogger.presentation.theme.platform_style.QApplication.instance", return_value=application):
                    configure_application_style()
                application.setStyle.assert_not_called()

    def test_other_platforms_keep_their_styles(self):
        for platform in ("darwin", "linux"):
            with self.subTest(platform=platform):
                application = Mock()
                with patch("worklogger.presentation.theme.platform_style.sys.platform", platform), \
                     patch("worklogger.presentation.theme.platform_style.QApplication.instance", return_value=application):
                    configure_application_style()
                application.setStyle.assert_not_called()

    def test_style_configuration_without_an_application_is_safe(self):
        with patch("worklogger.presentation.theme.platform_style.QApplication.instance", return_value=None):
            configure_application_style()


if __name__ == "__main__":
    unittest.main()
