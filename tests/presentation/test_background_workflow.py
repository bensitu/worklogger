"""Background availability, responsive loading, and animation lifetime."""

import os
import threading
import time
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QTimer, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QWidget

from tests.background_samples import (
    animated_background_bytes,
    animated_gif_background_bytes,
    still_background_bytes,
)
from tests.presentation.test_app_window import MemoryWorkLogRepository, _window
from worklogger.app.job_runner import CancellationToken, JobHandle
from worklogger.domain.settings.background import BackgroundImage, BackgroundState
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.images.background import (
    prepare_background,
    validate_background_data,
)
from tests.job_runner import ImmediateJobRunner
from worklogger.presentation.shell.background_controller import BackgroundController
from worklogger.presentation.shell.appearance_controller import WindowAppearanceController
from worklogger.presentation.theme.background import MainBackgroundWidget
from worklogger.presentation.theme.context import current_colors


class BackgroundWorkflowTests(unittest.TestCase):
    def test_surface_failure_releases_busy_state_and_allows_reloading(self):
        surface = self.surface()
        surface.set_background = Mock(side_effect=[RuntimeError("surface unavailable"), None])
        service = Mock()
        service.load.return_value = Result.success(BackgroundState())
        controller = BackgroundController(surface, service, available=True, job_runner=ImmediateJobRunner())
        self.assertTrue(controller.reload())
        self.assertFalse(controller.is_busy)
        self.assertFalse(controller.last_result.ok)
        self.assertTrue(controller.reload())
        self.assertTrue(controller.last_result.ok)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def surface(self):
        surface = MainBackgroundWidget()
        self.addCleanup(surface.deleteLater)
        self.addCleanup(surface.shutdown)
        self.addCleanup(surface.close)
        return surface

    def wait_until(self, condition):
        deadline = time.monotonic() + 3
        while not condition() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(condition())

    def test_explicitly_disabled_window_does_not_load_or_enable_stored_media(self):
        service = Mock()
        service.load.return_value = Result.success(BackgroundState(validate_background_data(animated_background_bytes()), True))
        window = _window(MemoryWorkLogRepository(), background_service=service)
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.close)
        window.show()
        self.app.processEvents()
        self.assertFalse(window.background_controller.available)
        self.assertFalse(window.background_controller.reload())
        self.assertFalse(window.background_controller.import_image("unused.png"))
        self.assertFalse(window.background_controller.set_options(enabled=True, opacity=50))
        self.assertFalse(window.background_controller.clear())
        self.assertFalse(window._background_surface.background_active)
        service.load.assert_not_called()

    def test_opening_settings_reuses_loaded_background_without_restarting_animation(self):
        from worklogger.presentation.settings import SettingsPage
        from tests.presentation.test_settings_presentation import MemorySettingsRepository, _view_model

        state = BackgroundState(validate_background_data(animated_background_bytes()), True, 70)
        service = Mock()
        service.load.return_value = Result.success(state)
        workflow = SimpleNamespace(create_page=lambda parent: SettingsPage(_view_model(MemorySettingsRepository()), parent))
        window = _window(MemoryWorkLogRepository(), settings_workflow=workflow,
                         background_service=service, background_images_available=True)
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.close)
        player = window._background_surface._player
        version = window._background_surface._version
        self.assertTrue(window.open_settings())
        service.load.assert_called_once()
        self.assertIs(window._background_surface._player, player)
        self.assertEqual(window._background_surface._version, version)
        controls = window.settings_page.background_settings
        self.assertTrue(controls.enabled_switch.isChecked())
        self.assertTrue(controls.enabled_switch.isEnabled())
        self.assertEqual(controls.opacity_slider.value(), 70)

    def test_window_appearance_keeps_media_across_material_changes_and_disposes_playback(self):
        old_palette, old_style = self.app.palette(), self.app.styleSheet()
        old_context = self.app.property("worklogger_theme_context")
        window = QWidget()
        self.addCleanup(window.deleteLater)
        surface = MainBackgroundWidget(window)
        state = BackgroundState(validate_background_data(animated_background_bytes()), True)
        service = SimpleNamespace(load=lambda: Result.success(state))
        controller = WindowAppearanceController(window, surface, background_service=service,
            background_images_available=True, job_runner=ImmediateJobRunner())
        try:
            controller.background.reload()
            for theme, dark in (("green", False), ("liquid_glass", True), ("custom", False)):
                colors = controller.apply(theme, dark=dark, custom_color="#ab1234")
                self.assertEqual(current_colors(), colors)
                self.assertTrue(surface.background_active)
                self.assertEqual(surface._state, state)
            controller.dispose()
            controller.dispose()
            self.assertIsNone(surface._player)
            self.assertFalse(controller.background.reload())
            self.assertIsNone(controller.apply("blue"))
        finally:
            controller.dispose()
            self.app.setPalette(old_palette)
            self.app.setStyleSheet(old_style)
            self.app.setProperty("worklogger_theme_context", old_context)

    def test_failed_loading_preserves_media_and_disposal_ignores_pending_results(self):
        state = BackgroundState(validate_background_data(still_background_bytes()), True)
        surface = self.surface()
        service = SimpleNamespace(load=lambda: Result.success(state))
        controller = BackgroundController(surface, service, available=True, job_runner=ImmediateJobRunner())
        self.assertTrue(controller.reload())
        self.assertTrue(surface.background_active)
        invalid = BackgroundImage(b"not an image", "png", 1280, 720)
        service.load = lambda: Result.success(BackgroundState(invalid, True))
        result = QSignalSpy(controller.completed)
        controller.reload()
        self.assertFalse(result.at(0)[0].ok)
        self.assertTrue(surface.background_active)

        class DeferredRunner:
            def submit(self, name, operation, *, on_complete):
                self.operation, self.complete = operation, on_complete
                self.cancelled = False
                return JobHandle(name, lambda: setattr(self, "cancelled", True))

        runner = DeferredRunner()
        empty_surface = self.surface()
        pending = BackgroundController(empty_surface, SimpleNamespace(load=lambda: Result.success(state)),
                                       available=True, job_runner=runner)
        self.assertTrue(pending.reload())
        self.assertFalse(pending.reload())
        ready = runner.operation(CancellationToken())
        pending.dispose()
        runner.complete(ready)
        self.assertTrue(runner.cancelled)
        self.assertFalse(empty_surface.background_active)
        self.assertFalse(pending.reload())
        self.assertFalse(pending.is_busy)

    def test_loading_runs_off_the_ui_thread_and_keeps_event_processing_alive(self):
        state = BackgroundState(validate_background_data(still_background_bytes()), True)
        started, release = threading.Event(), threading.Event()
        observed_threads = []
        main_thread = threading.get_ident()

        def load():
            observed_threads.append(threading.get_ident())
            started.set()
            release.wait(5)
            return Result.success(state)

        surface = self.surface()
        controller = BackgroundController(surface, SimpleNamespace(load=load), available=True)
        ticks = []
        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(lambda: ticks.append(True))
        timer.start()
        try:
            controller.reload()
            self.wait_until(started.is_set)
            self.wait_until(lambda: len(ticks) >= 3)
            self.assertNotEqual(observed_threads, [main_thread])
            self.assertTrue(controller.is_busy)
            release.set()
            self.wait_until(lambda: not controller.is_busy)
            self.assertTrue(surface.background_active)
        finally:
            release.set()
            timer.stop()
            controller._runner.shutdown(wait=True)

    def test_animation_pauses_when_hidden_and_survives_replacement_and_shutdown(self):
        state, frame = prepare_background(BackgroundState(validate_background_data(animated_background_bytes()), True)).value
        surface = self.surface()
        surface.set_background(state, frame)
        surface.show()
        frames = QSignalSpy(surface._player.frame_ready)
        self.wait_until(lambda: frames.count() >= 3)
        colors = {frames.at(index)[1].pixelColor(0, 0).name() for index in range(frames.count())}
        self.assertEqual(colors, {"#e84376", "#36b5a1"})
        version, current_frame = surface._version, surface._frame
        source_changes = QSignalSpy(surface._player.source_requested)
        surface.set_background(replace(state, opacity=35), frame)
        self.assertEqual(surface._version, version)
        self.assertEqual(surface._frame, current_frame)
        self.assertEqual(source_changes.count(), 0)
        surface.hide()
        count = frames.count()
        player = surface._player
        version = frames.at(count - 1)[0]
        player._mailbox.offer(version, frame)
        player._take_frame()
        self.assertEqual(frames.count(), count)
        QTest.qWait(200)
        self.assertEqual(frames.count(), count)
        surface.show()
        self.wait_until(lambda: frames.count() > count)
        self.app.applicationStateChanged.emit(Qt.ApplicationState.ApplicationInactive)
        QTest.qWait(100)
        count = frames.count()
        QTest.qWait(200)
        self.assertEqual(frames.count(), count)
        self.assertTrue(surface.background_active)
        self.app.applicationStateChanged.emit(Qt.ApplicationState.ApplicationActive)
        self.wait_until(lambda: frames.count() > count)
        version = frames.at(frames.count() - 1)[0]
        surface._player.failed.emit(version)
        surface._player.frame_ready.emit(version, frame)
        self.assertFalse(surface.background_active)
        still, still_frame = prepare_background(BackgroundState(validate_background_data(still_background_bytes()), True)).value
        surface.set_background(still, still_frame)
        QTest.qWait(180)
        count = frames.count()
        player._mailbox.offer(version, frame)
        player._take_frame()
        self.assertEqual(frames.count(), count)
        self.assertFalse(surface._state.image.animated)
        self.assertTrue(surface.background_active)
        surface.shutdown()
        surface.shutdown()
        player._mailbox.offer(version, frame)
        player._take_frame()
        self.assertEqual(frames.count(), count)
        self.assertIsNone(surface._player)
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_gif_animation_remains_active_across_repeated_loops(self):
        image = validate_background_data(animated_gif_background_bytes())
        self.assertEqual((image.format, image.width, image.height, image.frames), ("gif", 1280, 720, 2))
        state, frame = prepare_background(BackgroundState(image, True)).value
        surface = self.surface()
        surface.set_background(state, frame)
        frames = QSignalSpy(surface._player.frame_ready)
        surface.show()
        self.wait_until(lambda: frames.count() >= 5)
        self.assertTrue(surface.background_active)
        self.assertEqual({frames.at(index)[1].pixelColor(0, 0).name() for index in range(frames.count())},
                         {"#e84376", "#36b5a1"})

    def tearDown(self):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
