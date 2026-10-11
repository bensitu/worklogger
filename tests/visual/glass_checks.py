from dataclasses import replace
import os
from pathlib import Path
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QIODevice, QPoint, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from worklogger.infrastructure.i18n import set_language
from worklogger.presentation.theme.glass_surfaces import GlassLayer
from tests.visual.shell_checks import sample_window


class GlassLayoutChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_for_render(self, window):
        deadline = time.monotonic() + 5
        while window.glass_controller.is_rendering and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertFalse(window.glass_controller.is_rendering)

    def test_glass_panels_render_across_routes_and_restore_normal_themes(self):
        for language in ("en_US", "zh_CN", "ja_JP"):
            set_language(language)
            for dark in (False, True):
                window = sample_window()
                window.settings_page.theme_combo.setCurrentIndex(window.settings_page.theme_combo.findData("liquid_glass"))
                window.settings_page.mode_combo.setCurrentIndex(window.settings_page.mode_combo.findData("dark" if dark else "light"))
                window.refresh()
                window.show()
                try:
                    for width, height in ((880, 580), (1100, 700)):
                        window.resize(width, height)
                        for route in ("calendar", "analytics", "reports", "settings"):
                            window._switch_route(route)
                            self.app.processEvents()
                            self.wait_for_render(window)
                            if route == "calendar":
                                page = window.calendar_page
                                self.assertEqual(window.calendar_view.grid_frame.frameWidth(), 0)
                                self.assertFalse(page.right_panel.findChildren(GlassLayer, options=Qt.FindChildOption.FindDirectChildrenOnly))
                                self.assertFalse(window.entry_panel.findChildren(GlassLayer, options=Qt.FindChildOption.FindDirectChildrenOnly))
                                self.assertFalse(window.calendar_view.grid_frame.findChildren(GlassLayer, options=Qt.FindChildOption.FindDirectChildrenOnly))
                                margins = page.right_panel.layout().contentsMargins()
                                self.assertEqual((margins.left(), margins.right()), (12, 12))
                                for field in (page.selected_date_label, window.entry_panel.time_tabs,
                                              page.details_scroll, window.entry_panel.actions_widget, page.records_scroll):
                                    bounds = field.rect().translated(field.mapTo(page.right_panel, QPoint()))
                                    self.assertGreaterEqual(bounds.left(), 12)
                                    self.assertLessEqual(bounds.right(), page.right_panel.width() - 13)
                            elif route == "reports":
                                history = window.reports_page.history_panel
                                self.assertEqual(history.scroll_widget.palette().color(history.scroll_widget.backgroundRole()).alpha(), 0)
                            elif route == "settings":
                                settings = window.settings_page
                                for category in settings._category_pages:
                                    settings.category_nav.set_category(category)
                                    self.app.processEvents()
                                    self.wait_for_render(window)
                                    self.assertEqual(settings.category_stack.currentWidget().horizontalScrollBar().maximum(), 0)
                                    title = settings.findChild(QWidget, "settings_title_label")
                                    self.assertTrue(settings.rect().contains(title.geometry()))
                                    self.capture(window, f"{language}-glass-{dark}-settings-{category}-{width}")
                                settings.category_nav.set_category("appearance")
                                self.app.processEvents()
                                self.wait_for_render(window)
                            layers = [layer for layer in window.findChildren(GlassLayer) if layer.isVisible()]
                            self.assertTrue(layers)
                            self.assertTrue(any(not layer.image.isNull() for layer in layers))
                            for layer in layers:
                                self.assertEqual(layer.geometry(), layer.parentWidget().rect())
                                self.assertEqual(layer.parentWidget().property("glass_surface"), True)
                            self.capture(window, f"{language}-glass-{dark}-{route}-{width}")
                    window._config = replace(window._config, theme="blue")
                    window.apply_theme()
                    self.app.processEvents()
                    self.wait_for_render(window)
                    self.assertFalse(any(layer.isVisible() for layer in window.findChildren(GlassLayer)))
                    history = window.reports_page.history_panel
                    self.assertEqual(history.scroll_widget.palette().color(history.scroll_widget.backgroundRole()).alpha(), 0)
                finally:
                    window.close()
                    window.deleteLater()
        set_language("en_US")

    def capture(self, window, name):
        directory = os.environ.get("WORKLOGGER_SCREENSHOTS")
        if directory:
            Path(directory).mkdir(parents=True, exist_ok=True)
            self.assertTrue(window.grab().save(str(Path(directory) / f"{name}.png")))

    def test_minimal_glass_view_uses_user_backgrounds_without_blurring_editors(self):
        from datetime import date
        from tests.presentation.test_app_window import _entry_model, MemoryWorkLogRepository
        from worklogger.domain.settings.background import BackgroundState
        from worklogger.infrastructure.images.background import validate_background_data
        from worklogger.presentation.shell import MinimalView, MinimalViewConfig
        image = QImage(1280, 720, QImage.Format.Format_RGB32)
        painter = QPainter(image)
        painter.fillRect(0, 0, 640, 720, QColor("#b27f96"))
        painter.fillRect(640, 0, 640, 720, QColor("#7db6c1"))
        painter.end()
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        self.assertTrue(image.save(buffer, "PNG"))
        state = BackgroundState(validate_background_data(bytes(buffer.data())), True, 100)
        for dark in (False, True):
            view = MinimalView(time_entry_view_model=_entry_model(MemoryWorkLogRepository()),
                               config=MinimalViewConfig(theme="liquid_glass", dark=dark, today=date(2026, 4, 20),
                                                        confirm_discard_changes=lambda: True))
            try:
                view._background_surface.set_background(state, image)
                view.refresh()
                view.entry_panel.content_input.setPlainText("Readable text")
                view.show()
                self.app.processEvents()
                self.wait_for_render(view)
                layer = view.entry_panel.findChild(GlassLayer)
                self.assertIsNotNone(layer)
                self.assertFalse(layer.image.isNull())
                self.assertEqual(view.entry_panel.content_input.toPlainText(), "Readable text")
                directory = os.environ.get("WORKLOGGER_SCREENSHOTS")
                if directory:
                    Path(directory).mkdir(parents=True, exist_ok=True)
                    self.assertTrue(view.grab().save(str(Path(directory) / f"minimal-glass-{dark}.png")))
            finally:
                view.close()
                if view.glass_controller._runner is not None:
                    view.glass_controller._runner.shutdown(wait=True)
                view.deleteLater()
