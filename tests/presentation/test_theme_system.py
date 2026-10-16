"""Theme definitions, reusable materials and configuration fallbacks."""

from dataclasses import replace
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from worklogger.config.themes import AccentColors, SurfaceOverrides, THEME_CATALOG, ThemeDefinition, normalize_theme
from worklogger.presentation.theme import ThemeEngine
from worklogger.presentation.theme.calendar_styles import calendar_cell_style
from worklogger.presentation.theme.palettes import build_palette
from worklogger.presentation.theme.stylesheets import application_stylesheet
from worklogger.presentation.theme.context import current_colors
from worklogger.presentation.theme.materials import CalendarColors, material_profile
from worklogger.presentation.theme.qt_palette import qt_palette


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

    def test_surface_overrides_share_material_rules_without_changing_other_themes(self):
        definition = replace(THEME_CATALOG["liquid_glass"], key="studio", label="Studio",
                             light_overrides=SurfaceOverrides(surface="#abcdef", danger="#a01234"))
        original = build_palette(THEME_CATALOG["liquid_glass"], False, None)
        colors = build_palette(definition, False, None)
        self.assertEqual((colors.surface, colors.danger), ("#abcdef", "#a01234"))
        self.assertEqual(colors.input_border, original.input_border)
        self.assertEqual(calendar_cell_style({"holiday"}, colors).foreground, colors.danger)
        self.assertEqual(build_palette(definition, True, None).surface,
                         build_palette(THEME_CATALOG["liquid_glass"], True, None).surface)
        self.assertEqual(build_palette(THEME_CATALOG["liquid_glass"], False, None), original)
        self.assertNotIn("{{", application_stylesheet(colors))
        for override in ({"not_a_role": "#123456"}, {"surface": "rgba(1,2,3,4)"}):
            with self.assertRaises(ValueError):
                SurfaceOverrides(**override)

    def test_materials_reject_invalid_calendar_and_rendering_configuration(self):
        for changes in ({"alpha": 256}, {"border_width": -1}, {"foreground": "not_a_role"}):
            with self.assertRaises(ValueError):
                replace(CalendarColors("surface", "text", "border"), **changes)
        solid = material_profile("solid")
        for changes in ({"calendar_dark": ()}, {"refraction": True},
                        {"stylesheet_fragments": ("../styles.qss",)}, {"backdrop_light": ("#123456",)}):
            with self.assertRaises(ValueError):
                replace(solid, **changes)

    def test_qt_palette_values_can_be_mutated_without_changing_cached_themes(self):
        for theme in THEME_CATALOG:
            for dark in (False, True):
                colors = ThemeEngine().palette(theme, dark=dark)
                first, second = qt_palette(colors), qt_palette(colors)
                self.assertEqual(first.color(QPalette.ColorRole.Highlight).name(), colors.accent)
                self.assertEqual(first.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text).name(), colors.disabled_text)
                for role in (QPalette.ColorRole.PlaceholderText, QPalette.ColorRole.HighlightedText):
                    self.assertEqual(first.color(QPalette.ColorGroup.Disabled, role).name(), colors.disabled_text)
                for role in (QPalette.ColorRole.Base, QPalette.ColorRole.Button, QPalette.ColorRole.AlternateBase):
                    self.assertEqual(first.color(QPalette.ColorGroup.Disabled, role).name(), colors.disabled_background)
                self.assertEqual(first.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight).name(), colors.border)
                first.setColor(QPalette.ColorRole.Highlight, QColor("#012345"))
                self.assertEqual(second.color(QPalette.ColorRole.Highlight).name(), colors.accent)
                self.assertEqual(qt_palette(colors), second)

    def test_unknown_choices_and_invalid_custom_colors_use_defaults(self):
        engine = ThemeEngine()
        self.assertEqual(normalize_theme(" BLUE "), "blue")
        self.assertEqual(engine.palette("missing"), engine.palette("blue"))
        self.assertEqual(engine.palette("custom", custom_color="invalid"), engine.palette("custom"))
