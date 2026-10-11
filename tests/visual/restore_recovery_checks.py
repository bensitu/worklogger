"""Opt-in recovery dialog layout, disabled choices, and keyboard defaults."""

import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect
from PySide6.QtWidgets import QApplication, QMessageBox

from worklogger.domain.shared.recovery import RestoreRecoveryChoices
from worklogger.infrastructure.i18n import get_language, set_language
from worklogger.presentation.widgets.restore_recovery import choose_restore_recovery
from worklogger.presentation.theme import ThemeEngine, install_bundled_fonts


class RestoreRecoveryLayoutChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        install_bundled_fonts()

    def test_localized_recovery_choices_fit_and_default_to_cancel(self):
        old_language, old_style, old_palette = get_language(), self.app.styleSheet(), self.app.palette()
        try:
            for language in ("en_US", "zh_CN", "ja_JP"):
                set_language(language)
                for dark in (False, True):
                    engine = ThemeEngine()
                    self.app.setPalette(engine.qt_palette(dark=dark))
                    self.app.setStyleSheet(engine.application_stylesheet(dark=dark))

                    def inspect(dialog, language=language, dark=dark):
                        dialog.show()
                        self.app.processEvents()
                        cancel = dialog.button(QMessageBox.StandardButton.Cancel)
                        self.assertIs(dialog.defaultButton(), cancel)
                        self.assertIs(dialog.escapeButton(), cancel)
                        self.assertEqual(sum(button.isEnabled() for button in dialog.buttons()), 2)
                        for button in dialog.buttons():
                            bounds = QRect(button.mapTo(dialog, QPoint()), button.size())
                            self.assertTrue(dialog.rect().contains(bounds))
                            self.assertGreaterEqual(button.width(), button.fontMetrics().horizontalAdvance(button.text()))
                        destination = os.environ.get("WORKLOGGER_SCREENSHOTS")
                        if destination:
                            directory = Path(destination)
                            directory.mkdir(parents=True, exist_ok=True)
                            self.assertTrue(dialog.grab().save(str(directory / f"{language}-recovery-{'dark' if dark else 'light'}.png")))
                        dialog.close()
                        dialog.deleteLater()
                        return 0

                    with patch.object(QMessageBox, "exec", inspect):
                        self.assertIsNone(choose_restore_recovery(RestoreRecoveryChoices(True, False)))
                    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        finally:
            set_language(old_language)
            self.app.setPalette(old_palette)
            self.app.setStyleSheet(old_style)
