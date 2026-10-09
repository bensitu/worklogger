"""Avatar cropping, safe persistence, circular display, and default restoration."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog

from tests.presentation.test_settings_presentation import MemorySettingsRepository, _view_model
from worklogger.infrastructure.images.avatar import decode_avatar, load_avatar_image
from worklogger.presentation.settings import SettingsPage
from worklogger.presentation.widgets.avatar import AvatarCropDialog, avatar_pixmap
from worklogger.presentation.widgets.sidebar import SidebarWidget


class AccountAvatarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_upload_crop_save_preview_and_default_restore(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        image = QImage(600, 400, QImage.Format.Format_RGB32)
        image.fill(QColor("#ec4373"))
        image.setText("Description", "Private source metadata")
        source = Path(directory) / "sample.png"
        self.assertTrue(image.save(str(source)))
        self.assertTrue(load_avatar_image(source).ok)
        repository = MemorySettingsRepository()
        model = _view_model(repository)
        page, sidebar = SettingsPage(model), SidebarWidget()
        self.addCleanup(page.deleteLater)
        self.addCleanup(sidebar.deleteLater)
        page.settings_changed.connect(lambda state: sidebar.set_avatar(state.profile_avatar_png))
        page.refresh()

        def select_crop(dialog):
            dialog.zoom_slider.setValue(150)
            QTest.keyClick(dialog.canvas, Qt.Key.Key_Right)
            return QDialog.DialogCode.Accepted

        with patch.object(QFileDialog, "getOpenFileName", return_value=(str(source), "")), patch.object(AvatarCropDialog, "exec", select_crop):
            page.change_avatar_button.click()
        encoded = model.load().value.profile_avatar_png
        self.assertTrue(encoded)
        decoded = decode_avatar(encoded)
        self.assertEqual((decoded.width(), decoded.height()), (256, 256))
        self.assertNotIn("Private source metadata", decoded.text("Description"))
        pixels = sidebar.profile_avatar_label.pixmap().toImage()
        self.assertEqual(pixels.pixelColor(0, 0).alpha(), 0)
        self.assertGreater(pixels.pixelColor(36, 36).alpha(), 0)
        page.refresh()
        self.assertTrue(page.reset_avatar_button.isEnabled())
        page.reset_avatar_button.click()
        self.assertEqual(model.load().value.profile_avatar_png, "")
        self.assertFalse(page.reset_avatar_button.isEnabled())
        self.assertFalse(sidebar.profile_avatar_label.pixmap().isNull())

    def test_invalid_or_cancelled_input_preserves_the_saved_avatar(self):
        model = _view_model(MemorySettingsRepository())
        image = QImage(20, 20, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.green)
        from worklogger.infrastructure.images.avatar import encode_avatar
        original = encode_avatar(image)
        model.set_avatar(original)
        self.assertFalse(model.set_avatar("not an image").ok)
        self.assertEqual(model.load().value.profile_avatar_png, original)
        self.assertIsNone(decode_avatar("not an image"))
        self.assertIsNone(decode_avatar("x" * (512 * 1024 + 1)))
        self.assertFalse(avatar_pixmap("not an image").isNull())
        page = SettingsPage(model)
        self.addCleanup(page.deleteLater)
        page.refresh()
        with patch.object(QFileDialog, "getOpenFileName", return_value=("", "")):
            page.change_avatar_button.click()
        self.assertEqual(model.load().value.profile_avatar_png, original)
