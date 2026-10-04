from dataclasses import replace
from datetime import date
import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QHBoxLayout, QWidget

from worklogger.infrastructure.i18n import set_language
from worklogger.presentation.theme import ThemeEngine
from worklogger.presentation.widgets.combo_chart import chart_palette
from worklogger.presentation.widgets.progress_cards import DonutGauge, DonutProgressCard
from tests.presentation.test_ui_layout import sample_window


class ProgressCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        set_language("en_US")

    def test_percentage_preserves_values_above_target(self):
        gauge = DonutGauge()
        for progress, expected in ((0, "0%"), (0.75, "75%"), (1, "100%"),
                                   (213.5 / 168, "127%"), (526 / 504, "104%"),
                                   (2, "200%"), (2.5, "250%"), (10, "1000%"),
                                   (-1, "0%"), (float("nan"), "0%"), (float("inf"), "0%")):
            with self.subTest(progress=progress):
                gauge.set_progress(progress)
                self.assertEqual(gauge.percentage_text, expected)
                self.assertEqual(gauge.accessibleName(), expected)
                self.assertEqual(gauge.size().width(), 80)

    def test_overflow_arc_is_visible_and_distinct_in_both_color_modes(self):
        for dark in (False, True):
            for accent in ("#4f8ef7", "#d97706"):
                gauge = DonutGauge()
                gauge.setPalette(ThemeEngine().qt_palette("custom", dark=dark, custom_color=accent))
                colors = chart_palette(gauge)
                for progress in (0.75, 1.0, 1.27, 2.0, 2.5):
                    gauge.set_progress(progress)
                    image = gauge.grab().toImage()
                    overflow_pixels = sum(
                        image.pixelColor(x, y).name() in (colors.warning, colors.success)
                        for x in range(image.width()) for y in range(image.height())
                    )
                    self.assertEqual(overflow_pixels > 0, progress > 1, (dark, accent, progress))
                    self.assertTrue(any(image.pixelColor(x, y).name() == colors.accent
                                        for x in range(image.width()) for y in range(image.height())))
                gauge.close()

    def test_period_titles_are_localized_and_zero_target_is_safe(self):
        expected = {
            "en_US": ("Monthly Hours", "Quarterly Hours", "Annual Hours"),
            "ja_JP": ("月間労働時間", "四半期労働時間", "年間労働時間"),
            "ko_KR": ("월간 근무 시간", "분기 근무 시간", "연간 근무 시간"),
            "zh_CN": ("月度工时", "季度工时", "年度工时"),
            "zh_TW": ("每月工時", "季度工時", "年度工時"),
        }
        for language, titles in expected.items():
            set_language(language)
            window = sample_window()
            try:
                page = window.analytics_page
                self.assertTrue(page.refresh(date(2026, 4, 21)))
                for scope, title in zip(("monthly", "quarterly", "annual"), titles):
                    page.scope_control.set_value(scope)
                    self.assertTrue(page.refresh())
                    self.assertEqual(page.monthly_hours_card.title_label.text(), title)
                state = replace(page._dashboard, target_hours=168,
                                stats=replace(page._dashboard.stats, total_hours=213.5))
                page._set_state(state)
                self.assertEqual(page.monthly_hours_card.gauge.percentage_text, "127%")
                page._set_state(replace(state, target_hours=0))
                self.assertEqual(page.monthly_hours_card.gauge.percentage_text, "0%")
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()

    def test_progress_cards_render_without_overlapping_text(self):
        set_language("en_US")
        for dark in (False, True):
            original_stylesheet = self.app.styleSheet()
            self.app.setStyleSheet(ThemeEngine().application_stylesheet("blue", dark=dark))
            surface = QWidget()
            surface.setPalette(ThemeEngine().qt_palette("blue", dark=dark))
            surface.setAutoFillBackground(True)
            layout = QHBoxLayout(surface)
            cards = []
            for progress in (0.75, 1, 213.5 / 168, 2.5):
                card = DonutProgressCard("Monthly Hours")
                card.set_value(f"{progress * 168:.1f}h", "of 168.0h goal", progress)
                layout.addWidget(card)
                cards.append(card)
            surface.resize(1080, 160)
            surface.show()
            try:
                self.app.processEvents()
                for card in cards:
                    self.assertTrue(card.rect().contains(card.gauge.geometry()))
                    self.assertLess(card.value_label.geometry().right(), card.gauge.geometry().left())
                directory = os.environ.get("WORKLOGGER_SCREENSHOTS")
                if directory:
                    destination = Path(directory)
                    destination.mkdir(parents=True, exist_ok=True)
                    self.assertTrue(surface.grab().save(str(destination / f"progress-{'dark' if dark else 'light'}.png")))
            finally:
                surface.close()
                self.app.setStyleSheet(original_stylesheet)


if __name__ == "__main__":
    unittest.main()
