"""Opt-in background cover, opacity, foreground and page rendering checks."""

import os
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from tests.background_samples import still_background_bytes
from tests.presentation.qt_support import dispose_test_windows
from tests.presentation.test_app_window import MemoryWorkLogRepository, _window
from tests.presentation.test_settings_presentation import (
    MemorySettingsRepository,
    _view_model,
)
from worklogger.domain.settings.background import BackgroundState
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import (
    available_languages,
    get_language,
    set_language,
)
from worklogger.infrastructure.images.background import (
    prepare_background,
    validate_background_data,
)
from worklogger.presentation.settings import SettingsPage
from worklogger.presentation.theme import (
    ThemeEngine,
    configure_application_style,
    install_bundled_fonts,
)
from worklogger.presentation.theme.background import MainBackgroundWidget


class BackgroundImagesLayoutChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        configure_application_style()
        install_bundled_fonts()

    def tearDown(self):
        dispose_test_windows()

    def test_center_cover_and_opacity_preserve_theme_color_without_letterboxing(self):
        image = QImage(1280, 720, QImage.Format.Format_RGB32)
        image.fill(QColor("#36b5a1"))
        painter = QPainter(image)
        painter.fillRect(0, 0, 260, 720, QColor("#e84376"))
        painter.fillRect(1020, 0, 260, 720, QColor("#e84376"))
        painter.end()
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        self.assertTrue(image.save(buffer, "PNG"))
        media = validate_background_data(bytes(buffer.data()))
        surface = MainBackgroundWidget()
        try:
            surface.set_background(BackgroundState(media, True, 100), image)
            surface.resize(400, 400)
            surface.show()
            self.app.processEvents()
            rendered = surface.grab().toImage()
            for x, y in ((1, 1), (398, 1), (1, 398), (398, 398), (200, 200)):
                self.assertEqual(rendered.pixelColor(x, y).name(), "#36b5a1")
            surface.resize(900, 200)
            self.app.processEvents()
            rendered = surface.grab().toImage()
            self.assertEqual(rendered.pixelColor(1, 100).name(), "#e84376")
            self.assertEqual(rendered.pixelColor(898, 100).name(), "#e84376")
            self.assertEqual(rendered.pixelColor(450, 100).name(), "#36b5a1")
            for dark in (False, True):
                base = QColor(ThemeEngine().palette(dark=dark).surface)
                surface.set_base_color(base)
                for opacity in (0, 50, 100):
                    surface.set_background(BackgroundState(media, True, opacity), image)
                    self.app.processEvents()
                    actual = surface.grab().toImage().pixelColor(450, 100)
                    expected = [round(channel * opacity / 100 + background * (1 - opacity / 100))
                                for channel, background in zip(QColor("#36b5a1").getRgb()[:3], base.getRgb()[:3])]
                    for observed, reference in zip(actual.getRgb()[:3], expected):
                        self.assertLessEqual(abs(observed - reference), 1)
                    self.assertEqual(surface.background_active, opacity > 0)
        finally:
            surface.close()
            surface.deleteLater()

    def test_all_main_pages_show_background_without_changing_foreground_or_geometry(self):
        engine = ThemeEngine()
        old_language, old_style, old_palette = get_language(), self.app.styleSheet(), self.app.palette()
        media = validate_background_data(still_background_bytes())
        state = BackgroundState(media, True, 50)
        service = SimpleNamespace(load=lambda: Result.success(state))
        try:
            for language in available_languages():
                set_language(language)
                for dark in (False, True):
                    workflow = SimpleNamespace(create_page=lambda parent: SettingsPage(_view_model(MemorySettingsRepository()), parent))
                    window = _window(MemoryWorkLogRepository(), settings_workflow=workflow,
                                     background_service=service, background_images_available=True)
                    try:
                        window._config = replace(window._config, dark=dark)
                        window.apply_theme()
                        window.refresh()
                        window.show()
                        for width, height in ((880, 580), (1280, 820)):
                            window.resize(width, height)
                            self.app.processEvents()
                            before = window.entry_panel.content_input.size()
                            for route, index in window._page_routes.items():
                                page = window.settings_page if route == "settings" else window.page_stack.widget(index)
                                window.page_stack.setCurrentWidget(page)
                                self.app.processEvents()
                                page = window.page_stack.currentWidget()
                                if route == "settings":
                                    controls = window.settings_page.background_settings
                                    section = window.settings_page.category_stack.currentWidget()
                                    section.ensureWidgetVisible(controls)
                                    self.app.processEvents()
                                    self.assertFalse(controls.isHidden())
                                    self.assertGreaterEqual(controls.opacity_slider.width(), 80)
                                    for button in (controls.upload_button, controls.remove_button):
                                        self.assertTrue(controls.options_widget.rect().contains(button.geometry()))
                                        self.assertGreaterEqual(button.width(), button.fontMetrics().horizontalAdvance(button.text()) + 40)
                                surface = window._background_surface
                                rendered = surface.grab().toImage()
                                pixel = rendered.pixelColor(3, 3)
                                base = QColor(engine.palette(dark=dark).surface)
                                reference = [(channel + background) / 2 for channel, background in
                                             zip(QColor("#36b5a1").getRgb()[:3], base.getRgb()[:3])]
                                for observed, expected in zip(pixel.getRgb()[:3], reference):
                                    self.assertLessEqual(abs(observed - expected), 1, (language, dark, route))
                                self.assertTrue(surface.rect().contains(page.geometry()))
                                self.capture(window, f"{language}-background-{'dark' if dark else 'light'}-{route}-{width}")
                            window.page_stack.setCurrentWidget(window.calendar_page)
                            self.app.processEvents()
                            self.assertEqual(window.entry_panel.content_input.size(), before)
                            input_pixels = window.entry_panel.content_input.grab().toImage()
                            self.assertEqual(input_pixels.pixelColor(15, 5).name(), engine.palette(dark=dark).input_background)
                            disabled, frame = prepare_background(BackgroundState(media, False)).value
                            window._background_surface.set_background(disabled, frame)
                            self.app.processEvents()
                            self.assertEqual(window._background_surface.grab().toImage().pixelColor(3, 3).name(), base.name())
                            self.assertEqual(window.entry_panel.content_input.size(), before)
                            enabled, frame = prepare_background(state).value
                            window._background_surface.set_background(enabled, frame)
                    finally:
                        window.close()
                        window.deleteLater()
        finally:
            set_language(old_language)
            self.app.setPalette(old_palette)
            self.app.setStyleSheet(old_style)

    def capture(self, widget, name):
        destination = os.environ.get("WORKLOGGER_SCREENSHOTS")
        if destination:
            path = Path(destination)
            path.mkdir(parents=True, exist_ok=True)
            self.assertTrue(widget.grab().save(str(path / f"{name}.png")))

    def test_background_options_collapse_and_enabled_empty_state_keep_theme_surface(self):
        old_language, old_style, old_palette = get_language(), self.app.styleSheet(), self.app.palette()
        try:
            for language in ("en_US", "zh_CN"):
                set_language(language)
                for dark in (False, True):
                    service = SimpleNamespace(load=lambda: Result.success(BackgroundState()))
                    workflow = SimpleNamespace(create_page=lambda parent: SettingsPage(_view_model(MemorySettingsRepository()), parent))
                    window = _window(MemoryWorkLogRepository(), settings_workflow=workflow,
                                     background_service=service, background_images_available=True)
                    try:
                        window._config = replace(window._config, dark=dark)
                        window.apply_theme()
                        window.resize(880, 580)
                        window.show()
                        window.page_stack.setCurrentWidget(window.settings_page)
                        controls = window.settings_page.background_settings
                        section = window.settings_page.category_stack.currentWidget()
                        for enabled in (False, True):
                            service.load = lambda enabled=enabled: Result.success(BackgroundState(enabled=enabled))
                            window.background_controller.reload()
                            section.ensureWidgetVisible(controls)
                            self.app.processEvents()
                            self.assertEqual(controls.options_widget.isHidden(), not enabled)
                            self.assertTrue(controls.enabled_switch.isEnabled())
                            self.assertEqual(controls.upload_button.isEnabled(), enabled)
                            self.assertFalse(window._background_surface.background_active)
                            base = ThemeEngine().palette(dark=dark).surface
                            self.assertEqual(window._background_surface.grab().toImage().pixelColor(3, 3).name(), base)
                            self.capture(window, f"{language}-{'dark' if dark else 'light'}-empty-{'enabled' if enabled else 'disabled'}")
                    finally:
                        window.close()
                        window.deleteLater()
        finally:
            set_language(old_language)
            self.app.setPalette(old_palette)
            self.app.setStyleSheet(old_style)
