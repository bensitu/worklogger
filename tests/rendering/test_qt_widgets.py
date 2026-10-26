"""Widget rendering, theme adaptation, and bundled resource contracts."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QFont, QIcon, QPalette
from PySide6.QtWidgets import QApplication

from worklogger.presentation.theme import ThemeEngine
from worklogger.presentation.theme.fonts import _application_font
from worklogger.presentation.widgets import SettingsNav
from worklogger.presentation.widgets.assets import application_icon_path, asset_path
from worklogger.presentation.widgets.icons import ui_icon


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


class WidgetRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = _app()

    def test_settings_navigation_coalesces_label_layout_and_tracks_font_changes(self):
        class MeasuredNavigation(SettingsNav):
            wraps = 0

            def _wrap_labels(self):
                self.wraps += 1
                super()._wrap_labels()

        navigation = MeasuredNavigation((("appearance", "Appearance and display preferences"),
                                         ("general", "Work schedules and record settings")))
        self.addCleanup(navigation.deleteLater)
        navigation.setFixedWidth(180)
        navigation.resize(180, 500)
        navigation.show()
        for _pass in range(3):
            self._app.processEvents()
        before = navigation.wraps
        for _selection in range(20):
            navigation.set_category("appearance")
        self._app.processEvents()
        self.assertEqual(navigation.wraps, before)
        navigation.set_category("general")
        navigation.set_category("appearance")
        navigation.set_category("general")
        self._app.processEvents()
        self.assertEqual(navigation.wraps, before + 1)
        self.assertEqual(navigation.category, "general")
        previous_height = navigation._buttons["general"].minimumHeight()
        original_style = self._app.styleSheet()
        self.addCleanup(self._app.setStyleSheet, original_style)
        self._app.setStyleSheet(original_style + "\nQFrame#settings_navigation_frame, "
            "QFrame#settings_navigation_frame QPushButton { font-size: 22px; }")
        for _pass in range(3):
            self._app.processEvents()
        self.assertGreater(navigation._buttons["general"].minimumHeight(), previous_height)
        self.assertTrue(navigation._buttons["general"].property("active"))

    def test_entry_type_options_preserve_values_and_follow_shared_classification_colors(self):
        from PySide6.QtWidgets import QComboBox
        from worklogger.domain.worklog.models import CustomEntryType, EntryType
        from worklogger.presentation.widgets.entry_type_options import add_entry_type_option

        app = _app()
        old_style, old_palette = app.styleSheet(), app.palette()
        old_context = app.property("worklogger_theme_context")
        combo = QComboBox()
        definitions = (*EntryType, *(CustomEntryType(f"custom:{index:032x}", category, category)
                                    for index, category in enumerate(("work", "break", "leave"), 1)))
        for definition in definitions:
            add_entry_type_option(combo, definition)
        combo.setCurrentIndex(combo.findData("meeting"))
        engine = ThemeEngine()
        try:
            for dark in (False, True):
                engine.apply_to(app, dark=dark)
                for index, definition in enumerate(definitions):
                    self.assertEqual(combo.itemData(index), definition.value)
                    icon = combo.itemIcon(index)
                    expected = engine.entry_type_color(definition, dark=dark)
                    self.assertEqual(icon.isNull(), expected is None)
                    if expected is None:
                        continue
                    image = icon.pixmap(combo.iconSize()).toImage()
                    opaque_colors = {image.pixelColor(x, y).name()
                                     for x in range(image.width()) for y in range(image.height())
                                     if image.pixelColor(x, y).alpha() == 255}
                    self.assertEqual(opaque_colors, {expected})
                    scaled = QIcon(icon).pixmap(combo.iconSize(), 2.0)
                    self.assertEqual(scaled.devicePixelRatio(), 2.0)
                    disabled = icon.pixmap(combo.iconSize(), QIcon.Mode.Disabled).toImage()
                    self.assertLessEqual(max(disabled.pixelColor(x, y).alpha()
                                             for x in range(disabled.width())
                                             for y in range(disabled.height())), 115)
                self.assertEqual(combo.currentData(), "meeting")
        finally:
            combo.deleteLater()
            app.setStyleSheet(old_style)
            app.setPalette(old_palette)
            app.setProperty("worklogger_theme_context", old_context)

    def test_button_icons_follow_text_through_role_theme_and_enabled_changes(self):
        from PySide6.QtWidgets import QPushButton, QToolButton
        from worklogger.presentation.widgets.icons import set_button_icon
        from worklogger.presentation.theme.widget_style import refresh_style
        app = _app()
        original_style, original_palette = app.styleSheet(), app.palette()
        engine = ThemeEngine()
        try:
            for button_type in (QPushButton, QToolButton):
                button = button_type()
                set_button_icon(button, "file-text", format_label="MD" if button_type is QToolButton else "")
                for theme, dark in (("blue", False), ("blue", True), ("green", False), ("green", True)):
                    app.setPalette(engine.qt_palette(theme, dark=dark))
                    app.setStyleSheet(engine.application_stylesheet(theme, dark=dark))
                    colors = engine.palette(theme, dark=dark)
                    for variant in ("outline", "primary", "ghost", "danger"):
                        button.setProperty("variant", variant)
                        for enabled in (True, False):
                            button.setEnabled(enabled)
                            refresh_style(button)
                            group = QPalette.ColorGroup.Active if enabled else QPalette.ColorGroup.Disabled
                            expected = button.palette().color(group, QPalette.ColorRole.ButtonText).name()
                            if enabled:
                                self.assertEqual(expected, "#ffffff" if variant == "primary" else colors.danger if variant == "danger" else colors.text)
                            self.assertEqual(button.font().weight(), QFont.Weight.DemiBold if variant == "primary" else
                                             QFont.Weight.Normal if variant == "ghost" else QFont.Weight.Medium)
                            image = button.icon().pixmap(QSize(20, 20), QIcon.Mode.Normal if enabled else QIcon.Mode.Disabled).toImage()
                            opaque_colors = {image.pixelColor(x, y).name() for x in range(image.width()) for y in range(image.height())
                                if image.pixelColor(x, y).alpha() == 255}
                            self.assertEqual(opaque_colors, {expected})
                icon = button.icon()
                button.deleteLater()
                from PySide6.QtCore import QCoreApplication, QEvent
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.assertFalse(icon.pixmap(QSize(20, 20)).isNull())
        finally:
            app.setStyleSheet(original_style)
            app.setPalette(original_palette)

    def test_icons_reuse_rendering_and_follow_palette_and_pixel_ratio(self) -> None:
        app = _app()
        original = app.palette()
        icon = ui_icon("clock")
        first = icon.pixmap(QSize(20, 20))
        self.assertFalse(first.isNull())
        self.assertEqual(first.cacheKey(), icon.pixmap(QSize(20, 20)).cacheKey())
        scaled = icon.pixmap(QSize(20, 20), 2.0)
        self.assertEqual(scaled.size(), QSize(40, 40))
        self.assertEqual(scaled.devicePixelRatio(), 2.0)
        rectangular = icon.pixmap(QSize(12, 24)).toImage()
        points = [(x, y) for x in range(rectangular.width()) for y in range(rectangular.height())
                  if rectangular.pixelColor(x, y).alpha() > 0]
        width = max(x for x, _y in points) - min(x for x, _y in points) + 1
        height = max(y for _x, y in points) - min(y for _x, y in points) + 1
        self.assertLessEqual(abs(width - height), 1)
        marked = ui_icon("copy", format_label="MD")
        first_marked = marked.pixmap(QSize(24, 24))
        self.assertNotEqual(first_marked.cacheKey(), ui_icon("copy").pixmap(QSize(24, 24)).cacheKey())
        self.assertEqual(first_marked.cacheKey(), marked.pixmap(QSize(24, 24)).cacheKey())
        for ratio in (1.0, 1.5, 2.0):
            scaled_marked = marked.pixmap(QSize(24, 24), ratio)
            self.assertEqual(scaled_marked.devicePixelRatio(), ratio)
            self.assertEqual(scaled_marked.size(), QSize(round(24 * ratio), round(24 * ratio)))
            image = scaled_marked.toImage()
            self.assertTrue(any(image.pixelColor(x, y).alpha() for x in range(image.width())
                                for y in range(round(7 * ratio))))
        changed = QPalette(original)
        changed.setColor(QPalette.ColorRole.ButtonText, QColor("#dc2626"))
        try:
            app.setPalette(changed)
            self.assertNotEqual(icon.pixmap(QSize(20, 20)).cacheKey(), first.cacheKey())
            self.assertFalse(icon.pixmap(QSize(20, 20), QIcon.Mode.Disabled).isNull())
        finally:
            app.setPalette(original)

    def test_application_font_never_keeps_invalid_point_size(self) -> None:
        base_font = QFont("Sans Serif")
        base_font.setPixelSize(14)

        font = _application_font("Noto Sans", base_font)

        self.assertEqual(font.family(), "Noto Sans")
        self.assertGreater(font.pointSize(), 0)

    def test_application_icon_path_uses_platform_specific_assets(self) -> None:
        windows_icon = application_icon_path("win32")
        macos_icon = application_icon_path("darwin")
        linux_icon = application_icon_path("linux")

        self.assertEqual(windows_icon.name, "worklogger.ico")
        self.assertEqual(macos_icon.name, "worklogger.icns")
        self.assertEqual(linux_icon.name, "worklogger.webp")
        self.assertTrue(windows_icon.exists())
        self.assertTrue(macos_icon.exists())
        self.assertTrue(linux_icon.exists())
        self.assertTrue(asset_path("icons/worklogger.webp").exists())
        self.assertTrue(asset_path("images/avatar.webp").exists())
        self.assertTrue(asset_path("images/worklogger_login_image.webp").exists())

    def test_all_bundled_action_icons_render_for_enabled_and_disabled_controls(self):
        from PySide6.QtSvg import QSvgRenderer
        from scripts.build_resources import bundled_resources
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        bundled = {Path(source) for source, _target in bundled_resources(root)}
        for path in asset_path("icons/ui").glob("*.svg"):
            with self.subTest(icon=path.stem):
                self.assertIn(path, bundled)
                self.assertTrue(QSvgRenderer(str(path)).isValid())
                icon = ui_icon(path.stem)
                for mode in (QIcon.Mode.Normal, QIcon.Mode.Disabled):
                    image = icon.pixmap(QSize(20, 20), mode).toImage()
                    self.assertTrue(any(image.pixelColor(x, y).alpha() > 0
                        for x in range(image.width()) for y in range(image.height())))
