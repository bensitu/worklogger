from dataclasses import replace
from datetime import date
import os
from pathlib import Path
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, qInstallMessageHandler
from PySide6.QtGui import QFontMetricsF, QPainter
from PySide6.QtWidgets import QApplication, QHBoxLayout, QScrollArea, QWidget

from worklogger.infrastructure.i18n import set_language
from worklogger.presentation.theme import ThemeEngine
from worklogger.presentation.widgets import combo_chart, progress_cards
from worklogger.presentation.widgets.combo_chart import chart_palette
from worklogger.presentation.widgets.progress_cards import DonutGauge, DonutProgressCard, OvertimeComparisonChart
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
                self.assertEqual(gauge.size().width(), 72)

    def test_overflow_arc_is_visible_and_distinct_in_both_color_modes(self):
        for dark in (False, True):
            for accent in ("#4f8ef7", "#d97706"):
                gauge = DonutGauge()
                gauge.setPalette(ThemeEngine().qt_palette("custom", dark=dark, custom_color=accent))
                gauge.ensurePolished()
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

    def test_complete_rings_have_a_narrow_visible_gap(self):
        gauge = DonutGauge()
        gauge.setPalette(ThemeEngine().qt_palette("blue"))
        gauge.set_progress(2)
        gauge.ensurePolished()
        colors = chart_palette(gauge)
        image = gauge.grab().toImage().scaled(72, 72)
        inner = [x for x in range(36, 72) if image.pixelColor(x, 36).name() == colors.accent]
        outer = [x for x in range(36, 72) if image.pixelColor(x, 36).name() == colors.warning]
        self.assertTrue(inner)
        self.assertTrue(outer)
        self.assertGreaterEqual(min(outer) - max(inner) - 1, 1)
        self.assertLessEqual(min(outer) - max(inner) - 1, 3)

    def test_additional_rings_show_each_hundred_percent_interval(self):
        captured = []

        class RecordingPainter(QPainter):
            def drawArc(self, rect, start, span):
                if start == 90 * 16:
                    captured.append((rect, span, self.pen().color().name(), self.pen().widthF()))
                return super().drawArc(rect, start, span)

        gauge = DonutGauge()
        gauge.setPalette(ThemeEngine().qt_palette("blue"))
        for progress, spans in ((2, (-5760, -5760)), (2.01, (-5760, -5760, -57)),
                                (2.5, (-5760, -5760, -2880)), (3, (-5760,) * 3),
                                (3.5, (-5760,) * 3 + (-2880,)), (10, (-5760,) * 10)):
            captured.clear()
            gauge.set_progress(progress)
            with patch.object(progress_cards, "QPainter", RecordingPainter):
                gauge.grab()
            with self.subTest(progress=progress):
                self.assertEqual(tuple(item[1] for item in captured), spans)
                for inner, outer in zip(captured, captured[1:]):
                    self.assertGreater(outer[0].width(), inner[0].width())
                    self.assertNotEqual(inner[2], outer[2])
                    gap = (outer[0].width() - inner[0].width() - inner[3] - outer[3]) / 2
                    self.assertGreater(gap, 0)
                    self.assertLessEqual(gap, 3)
                self.assertEqual(gauge.size().width(), 72)
        gauge.set_progress(1_000_000)
        captured.clear()
        with patch.object(progress_cards, "QPainter", RecordingPainter):
            gauge.grab()
        self.assertEqual(len(captured), 32)
        self.assertEqual(gauge.percentage_text, "100000000%")

    def test_overtime_bars_use_a_shared_scale_and_clear_zero_values(self):
        captured = []

        class RecordingPainter(QPainter):
            def drawRoundedRect(self, rect, *args):
                captured.append((rect, self.brush().color().name()))
                return super().drawRoundedRect(rect, *args)

        chart = OvertimeComparisonChart()
        chart.setPalette(ThemeEngine().qt_palette("blue"))
        for current, previous, expected in ((20, 10, (25, 50)), (10, 20, (50, 25)),
                                            (10, 10, (50, 50)), (0, 10, (50,)),
                                            (10, 0, (50,)), (0, 0, ())):
            captured.clear()
            chart.set_hours(current, previous)
            with patch.object(progress_cards, "QPainter", RecordingPainter):
                chart.grab()
            with self.subTest(current=current, previous=previous):
                self.assertEqual(tuple(rect.height() for rect, color in captured), expected)
                if len(captured) == 2:
                    self.assertLess(captured[0][0].right(), captured[1][0].left())
                    self.assertEqual(captured[0][0].bottom(), captured[1][0].bottom())
                    self.assertNotEqual(captured[0][1], captured[1][1])
                for rect, color in captured:
                    self.assertTrue(chart.rect().contains(rect.toAlignedRect()))
        for language, label in (("en_US", "Overtime comparison"), ("ja_JP", "残業時間の比較"),
                                ("ko_KR", "초과 근무 비교"), ("zh_CN", "加班工时对比"),
                                ("zh_TW", "加班工時對比")):
            set_language(language)
            chart.set_hours(70.5, 20)
            self.assertIn(label, chart.toolTip())
            self.assertIn("20.0h", chart.toolTip())
            self.assertIn("70.5h", chart.toolTip())
            self.assertEqual(chart.toolTip(), chart.accessibleName())

    def test_work_mode_total_is_painted_on_one_line(self):
        captured = []

        class RecordingPainter(QPainter):
            def drawText(self, *args):
                captured.append((args[-1], QFontMetricsF(self.font()).horizontalAdvance(args[-1]), args[0].width()))
                return super().drawText(*args)

        chart = combo_chart.DonutChart()
        chart.set_segments((("Normal", 2135.5),), keys=("normal",))
        for width in (220, 440):
            chart.resize(width, 180)
            with patch.object(combo_chart, "QPainter", RecordingPainter):
                chart.grab()
            text, measured, available = captured[-1]
            self.assertEqual(text, "2135h 30m")
            self.assertLessEqual(measured, available)

    def test_summary_titles_align_and_durations_fit_across_periods_and_languages(self):
        warnings = []
        previous_handler = qInstallMessageHandler(lambda kind, context, message: warnings.append(message))
        try:
            for language in ("en_US", "ja_JP", "ko_KR", "zh_CN", "zh_TW"):
                set_language(language)
                window = sample_window()
                try:
                    window.show()
                    window._switch_route("analytics")
                    page = window.analytics_page
                    for dark in (False, True):
                        window._config = replace(window._config, dark=dark)
                        window.apply_theme()
                        for width in (880, 1100, 1440):
                            window.resize(width, 700)
                            for scope, total, target in (("monthly", 213.5, 168),
                                                         ("quarterly", 526, 504),
                                                         ("annual", 2135.5, 2016)):
                                page.scope_control.set_value(scope)
                                self.assertTrue(page.refresh(date(2026, 5, 21)))
                                state = replace(page._dashboard, target_hours=target,
                                                stats=replace(page._dashboard.stats,
                                                              total_hours=total, overtime_hours=70.5),
                                                previous_stats=replace(page._dashboard.previous_stats,
                                                                       overtime_hours=20))
                                page._set_state(state)
                                self.app.processEvents()
                                with self.subTest(language=language, dark=dark, width=width, scope=scope):
                                    self.assertEqual(window.width(), width)
                                    titles = (page.monthly_hours_card.title_label, page.overtime_title_label,
                                              page.attendance_card.title_label, page.rest_card.title_label)
                                    offsets = [title.mapTo(title.parentWidget(), QPoint()).y() for title in titles]
                                    self.assertEqual(len(set(offsets)), 1, offsets)
                                    for label in (page.monthly_hours_card.value_label, page.overtime_value_label):
                                        self.assertFalse(label.wordWrap())
                                        self.assertNotIn("\n", label.text())
                                        font = label.fitted_font()
                                        self.assertLessEqual(QFontMetricsF(font).horizontalAdvance(label.text()), label.contentsRect().width())
                                        self.assertGreaterEqual(font.pixelSize(), 12)
                                    card = page.monthly_hours_card
                                    self.assertLess(card.title_label.geometry().bottom(), card.value_label.geometry().top())
                                    self.assertLess(card.value_label.geometry().right(), card.gauge.geometry().left())
                                    self.assertLess(page.overtime_value_label.geometry().right(), page.overtime_chart.geometry().left())
                                    self.assertTrue(page.overtime_card.rect().contains(page.overtime_chart.geometry()))
                                    self.assertIn("70.5h", page.overtime_chart.toolTip())
                                    self.assertIn(f"{state.previous_stats.overtime_hours:.1f}h", page.overtime_chart.toolTip())
                                    for scroll in page.findChildren(QScrollArea):
                                        self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
                                directory = os.environ.get("WORKLOGGER_SCREENSHOTS")
                                if directory and language in ("zh_CN", "en_US") and width == 1100:
                                    destination = Path(directory)
                                    destination.mkdir(parents=True, exist_ok=True)
                                    self.assertTrue(window.grab().save(str(destination / f"summary-{language}-{scope}-{'dark' if dark else 'light'}.png")))
                finally:
                    window.close()
                    window.deleteLater()
                    self.app.processEvents()
            self.assertFalse([message for message in warnings if "QFont::" in message or "QPainter::" in message], warnings)
        finally:
            qInstallMessageHandler(previous_handler)

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
            for progress in (0.75, 1, 213.5 / 168, 2.5, 3.5):
                card = DonutProgressCard("Monthly Hours")
                card.set_value(f"{progress * 168:.1f}h", "of 168.0h goal", progress)
                layout.addWidget(card)
                cards.append(card)
            surface.resize(1350, 160)
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
