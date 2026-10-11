"""Theme definitions, reusable materials and configuration fallbacks."""

from dataclasses import replace
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from worklogger.config.themes import AccentColors, THEME_CATALOG, ThemeDefinition, normalize_theme
from worklogger.presentation.theme import ThemeEngine
from worklogger.presentation.theme.calendar_styles import calendar_cell_style
from worklogger.presentation.theme.palettes import build_palette
from worklogger.presentation.theme.stylesheets import application_stylesheet
from worklogger.presentation.theme.context import current_colors


class ThemeSystemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_applied_theme_colors_ignore_transparent_widgets_and_follow_palette_changes(self):
        application = self.app
        old_palette, old_style = application.palette(), application.styleSheet()
        old_context = application.property("worklogger_theme_context")
        widget = QWidget()
        try:
            widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
            widget.setObjectName("combo_chart_widget")
            engine = ThemeEngine()
            for theme in ("blue", "liquid_glass"):
                for dark in (False, True):
                    colors = engine.apply_to(application, theme, dark=dark)
                    widget.ensurePolished()
                    self.assertEqual(current_colors(), colors)
                    self.assertEqual(widget.palette().color(widget.backgroundRole()).alpha(), 0)
            application.setPalette(engine.qt_palette("green"))
            self.assertFalse(current_colors().dark)
            self.assertEqual(current_colors().accent, engine.palette("green").accent)
        finally:
            widget.deleteLater()
            application.setPalette(old_palette)
            application.setStyleSheet(old_style)
            application.setProperty("worklogger_theme_context", old_context)

    def test_material_profiles_support_independent_theme_keys(self):
        for original in ("blue", "liquid_glass"):
            definition = replace(THEME_CATALOG[original], key="studio", label="Studio")
            for dark in (False, True):
                colors = build_palette(definition, dark, None)
                accents = definition.dark if dark else definition.light
                self.assertEqual(colors.theme, "studio")
                self.assertEqual(colors.material, definition.material)
                self.assertEqual(colors.accent, accents.accent)
                self.assertNotIn("{{", application_stylesheet(colors))
                for flags in ({"holiday"}, {"weekend"}, {"today"}, {"selected"}):
                    self.assertEqual(calendar_cell_style(flags, colors),
                                     ThemeEngine().calendar_cell_style(flags, theme=original, dark=dark))

    def test_definitions_reject_invalid_colors_and_incomplete_modes(self):
        with self.assertRaises(ValueError):
            AccentColors("url(image)", "#123456", "#123456", "#123456", "#123456")
        for changes in ({"key": "invalid key"}, {"material": "unknown"}, {"dark": None}):
            with self.assertRaises(ValueError):
                replace(THEME_CATALOG["blue"], **changes)
        self.assertTrue(ThemeDefinition("studio_custom", "Studio Custom").customizable)

    def test_unknown_choices_and_invalid_custom_colors_use_defaults(self):
        engine = ThemeEngine()
        self.assertEqual(normalize_theme(" BLUE "), "blue")
        self.assertEqual(engine.palette("missing"), engine.palette("blue"))
        self.assertEqual(engine.palette("custom", custom_color="invalid"), engine.palette("custom"))
