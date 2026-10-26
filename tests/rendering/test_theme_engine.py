"""Theme palette resolution and semantic classification indicators."""

import unittest

from PySide6.QtGui import QColor, QPalette

from worklogger.domain.worklog.models import CustomEntryType, EntryType
from worklogger.presentation.theme import ThemeEngine, normalize_hex_color


class ThemeEngineTests(unittest.TestCase):
    def test_theme_engine_preserves_palette_and_calendar_priority(self) -> None:
        engine = ThemeEngine()

        self.assertEqual(normalize_hex_color("ABCDEF"), "#abcdef")
        self.assertEqual(normalize_hex_color("invalid"), "#4f8ef7")
        palette = engine.palette("custom", custom_color="#123456")
        self.assertEqual(palette.accent, "#123456")
        self.assertIn("#123456", engine.application_stylesheet("custom", custom_color="#123456"))
        qt_palette = engine.qt_palette("custom", custom_color="#123456")
        self.assertEqual(qt_palette.color(QPalette.ColorRole.Highlight).name(), "#123456")

        style = engine.calendar_cell_style({"weekend", "holiday", "selected"})
        self.assertEqual(style.key, "selected")
        self.assertEqual(style.background, "#4f8ef7")
        self.assertEqual(
            engine.entry_type_color(EntryType.BUSINESS_TRIP),
            "#7865b6",
        )
        for dark in (False, True):
            colors = []
            for entry_type in EntryType:
                color = engine.entry_type_color(entry_type, dark=dark)
                self.assertIsNotNone(color)
                self.assertTrue(QColor(color).isValid())
                colors.append(color)
            self.assertEqual(len(colors), len(set(colors)))

    def test_custom_classification_colors_follow_stable_identity_within_semantic_categories(self):
        from dataclasses import replace

        engine = ThemeEngine()
        definitions = tuple(CustomEntryType(f"custom:{index:032x}", "Research") for index in range(1, 17))
        for dark in (False, True):
            colors = []
            for definition in definitions:
                expected = engine.entry_type_color(definition, dark=dark)
                self.assertTrue(QColor(expected).isValid())
                self.assertEqual(engine.entry_type_color(definition.value, dark=dark), expected)
                self.assertEqual(ThemeEngine().entry_type_color(definition, dark=dark), expected)
                for category in ("work", "break", "leave"):
                    changed = replace(definition, label="Revised", category=category, revision=3, archived=True)
                    color = engine.entry_type_color(changed, dark=dark)
                    self.assertEqual(color, engine.entry_type_color(definition.value, dark=dark, category=category))
                    self.assertEqual(color, engine.entry_type_color(replace(changed, label="Renamed"), dark=dark))
                    if category != "work":
                        self.assertNotEqual(color, expected)
                colors.append(expected)
            self.assertGreater(len(set(colors)), 1)

    def test_builtin_and_custom_indicators_use_muted_category_color_families(self):
        from worklogger.domain.worklog.models import CustomWorkMode
        engine = ThemeEngine()
        for dark in (False, True):
            for category, minimum, maximum in (("work", 185, 255), ("leave", 0, 50), ("break", 75, 175)):
                definitions = [item for item in EntryType if item.category == category]
                definitions.extend(CustomEntryType(f"custom:{index:032x}", "Example", category) for index in range(1, 65))
                if category == "work":
                    definitions.extend(CustomWorkMode(f"custom:{index:032x}", "Hybrid") for index in range(1, 17))
                for definition in definitions:
                    color = QColor(engine.entry_type_color(definition, dark=dark))
                    hue, saturation, _lightness, _alpha = color.getHsl()
                    self.assertTrue(minimum <= hue <= maximum, (category, color.name(), hue))
                    self.assertLess(saturation, 170)

    def test_theme_engine_uses_shared_templates_and_resolved_palettes(self) -> None:
        engine = ThemeEngine()

        for theme in ("blue", "pink", "green", "purple", "custom", "liquid_glass"):
            for mode in ("light", "dark"):
                stylesheet = engine.application_stylesheet(theme, dark=mode == "dark")
                self.assertIn("QPushButton", stylesheet)
                self.assertNotIn("{{", stylesheet)
                colors = engine.palette(theme, dark=mode == "dark")
                qt_palette = engine.qt_palette(theme, dark=mode == "dark")
                self.assertEqual(qt_palette.color(QPalette.ColorRole.AlternateBase).name(), colors.table_alternate)
                self.assertEqual(qt_palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText).name(),
                                 colors.disabled_text)

        stylesheet = engine.application_stylesheet("custom", custom_color="#123456")
        self.assertIn("#123456", stylesheet)
        self.assertIn("QPushButton[variant=\"primary\"]", stylesheet)
        self.assertNotIn("{{", stylesheet)
