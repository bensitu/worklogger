import os
from dataclasses import replace
import time
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QImage, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout

from worklogger.app.job_runner import CancellationToken, JobHandle
from worklogger.domain.shared.result import Result
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.presentation.theme import ThemeEngine
from worklogger.config.themes import THEME_CATALOG
from worklogger.presentation.theme.palettes import build_palette
from worklogger.presentation.theme.background import MainBackgroundWidget
from worklogger.presentation.theme.glass_surfaces import GlassThemeController
from worklogger.presentation.theme.native_glass import NativeGlassAdapter
from worklogger.presentation.widgets.card import CardFrame
from worklogger.presentation.settings import SettingsPage
from tests.presentation.test_settings_presentation import _view_model, MemorySettingsRepository


class DeferredRunner:
    def __init__(self):
        self.jobs = []

    def submit(self, name, job, *, on_complete):
        token = CancellationToken()
        self.jobs.append((job, on_complete, token))
        return JobHandle(str(len(self.jobs)), token.cancel)


class GlassThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_render_jobs_do_not_sample_child_content_or_survive_theme_changes(self):
        window = QWidget()
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.close)
        layout = QVBoxLayout(window)
        source = MainBackgroundWidget()
        layout.addWidget(source)
        source.setMinimumSize(400, 300)
        target = CardFrame(source)
        target.setGeometry(20, 20, 300, 120)
        for x in (20, 170):
            extra = CardFrame(source)
            extra.setGeometry(x, 160, 140, 100)
        foreground = QWidget(source)
        foreground.setGeometry(30, 30, 80, 40)
        palette = foreground.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#ff0000"))
        foreground.setPalette(palette)
        foreground.setAutoFillBackground(True)
        runner = DeferredRunner()
        controller = GlassThemeController(window, source, job_runner=runner)
        colors = build_palette(replace(THEME_CATALOG["liquid_glass"], key="studio_glass", label="Studio Glass"), False, None)
        controller.configure(colors)
        window.show()
        deadline = time.monotonic() + 1
        while len(runner.jobs) < 2 and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertEqual(len(runner.jobs), 2)
        sampled = source.backdrop(source.rect(), QSize(400, 300))
        self.assertNotEqual(sampled.pixelColor(50, 50).name(), "#ff0000")
        self.assertTrue(target.property("glass_surface"))
        controller.configure(ThemeEngine().palette("blue"))
        self.assertFalse(target.property("glass_surface"))
        result = QImage(30, 20, QImage.Format.Format_ARGB32)
        result.fill(QColor("#00ff00"))
        runner.jobs[0][1](Result.success(result))
        self.assertFalse(target.findChild(QWidget, "glass_surface_layer_widget").isVisible())
        controller.dispose()

    def test_native_adapter_removes_effects_and_restores_widget_state(self):
        target = QWidget()
        self.addCleanup(target.deleteLater)
        self.addCleanup(target.close)
        target.show()
        original = target.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        removed = []
        backend = SimpleNamespace(GlassOptions=lambda **options: options,
            BlendingMode=SimpleNamespace(WITHIN_WINDOW=1),
            prepare_widget_for_glass=lambda widget: widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground),
            apply_glass_to_widget=lambda widget, **options: setattr(widget, "resizeEvent", lambda _event: None) or 7,
            remove_glass_effect=lambda effect: removed.append(effect))
        def native_window(widget):
            widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            return None
        adapter = NativeGlassAdapter(target, backend_factory=lambda: (backend, native_window))
        self.assertTrue(adapter.apply())
        self.assertIn("resizeEvent", target.__dict__)
        adapter.remove()
        self.assertEqual(removed, [7])
        self.assertNotIn("resizeEvent", target.__dict__)
        self.assertEqual(target.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground), original)
        unsupported = NativeGlassAdapter(target, backend_factory=lambda: None)
        self.assertFalse(unsupported.apply())

    def test_render_failures_leave_readable_surfaces_without_repeated_jobs(self):
        window = QWidget()
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.close)
        source = MainBackgroundWidget(window)
        source.setGeometry(0, 0, 400, 300)
        target = CardFrame(source)
        target.setGeometry(20, 20, 300, 120)
        runner = DeferredRunner()
        controller = GlassThemeController(window, source, job_runner=runner)
        controller.configure(ThemeEngine().palette("liquid_glass"))
        window.show()
        QTest.qWait(120)
        self.assertTrue(runner.jobs)
        failure = Result.failure(InfrastructureError("glass_render_failed", "glass_render_failed"))
        for _job, callback, _token in tuple(runner.jobs):
            callback(failure)
        count = len(runner.jobs)
        source.frame_changed.emit()
        QTest.qWait(120)
        self.assertEqual(len(runner.jobs), count)
        self.assertFalse(controller.is_rendering)
        self.assertTrue(target.findChild(QWidget, "glass_surface_layer_widget").isVisible())
        controller.dispose()

    def test_theme_selection_persists_and_retains_readable_light_and_dark_colors(self):
        repository = MemorySettingsRepository()
        page = SettingsPage(_view_model(repository))
        self.addCleanup(page.deleteLater)
        page.refresh()
        index = page.theme_combo.findData("liquid_glass")
        self.assertGreaterEqual(index, 0)
        self.assertEqual(page.theme_combo.itemData(page.theme_combo.count() - 1), "custom")
        page.theme_combo.setCurrentIndex(index)
        self.assertEqual(repository.values[(1, "theme")], "liquid_glass")
        for dark in (False, True):
            colors = ThemeEngine().palette("liquid_glass", dark=dark)
            self.assertNotEqual(colors.text, colors.surface)
            self.assertNotEqual(colors.disabled_text, colors.text)
            self.assertNotEqual(colors.highlighted_text, colors.accent)
            self.assertNotIn("{{", ThemeEngine().application_stylesheet("liquid_glass", dark=dark))
