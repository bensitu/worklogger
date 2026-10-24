"""Background settings exercise real storage through the shell controller."""

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from tests.background_samples import animated_background_bytes, still_background_bytes
from tests.presentation.qt_support import wait_for_condition
from tests.presentation.test_app_window import MemoryWorkLogRepository, _window
from tests.presentation.test_settings_presentation import (
    MemorySettingsRepository,
    _view_model,
)
from worklogger.app.job_runner import CancellationToken, JobHandle
from worklogger.app.use_cases.backgrounds import BackgroundService
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.database import MigrationRunner, SQLiteConnectionFactory
from worklogger.infrastructure.images.background import QtBackgroundImageLoader
from worklogger.infrastructure.repositories.background_sqlite import (
    SQLiteBackgroundRepository,
)
from worklogger.presentation.settings import SettingsPage
from worklogger.presentation.shell.app_window import AppWindowConfig


class BackgroundSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        factory = SQLiteConnectionFactory(self.directory / "settings.db")
        MigrationRunner(factory).run_pending()
        with factory.transaction() as connection:
            connection.execute(
                "INSERT INTO users(id,username,username_key,password_hash,password_salt,created_at,password_changed_at) "
                "VALUES(1,'sample','sample','synthetic','synthetic','2026-10-11','2026-10-11')"
            )
        self.service = BackgroundService(1, SQLiteBackgroundRepository(factory), QtBackgroundImageLoader())
        workflow = SimpleNamespace(create_page=lambda parent: SettingsPage(_view_model(MemorySettingsRepository()), parent))
        self.window = _window(MemoryWorkLogRepository(), settings_workflow=workflow,
                              background_service=self.service, background_images_available=True)
        self.addCleanup(self.window.deleteLater)
        self.addCleanup(self.window.close)
        self.controls = self.window.settings_page.background_settings

    def upload(self, data):
        if not self.controls.enabled_switch.isChecked():
            self.controls.enabled_switch.setChecked(True)
        path = self.directory / "image"
        path.write_bytes(data)
        with patch("worklogger.presentation.settings.sections.background.QFileDialog.getOpenFileName",
                   return_value=(str(path), "")):
            self.controls.upload_button.click()

    def test_entry_is_enabled_by_default_and_media_preferences_survive_reload(self):
        self.assertTrue(AppWindowConfig().background_images_available)
        self.assertFalse(self.controls.isHidden())
        self.assertTrue(self.controls.enabled_switch.isEnabled())
        self.assertTrue(self.controls.options_widget.isHidden())
        self.assertFalse(self.controls.upload_button.isEnabled())
        self.controls.enabled_switch.setChecked(True)
        self.assertFalse(self.controls.options_widget.isHidden())
        self.assertTrue(self.controls.upload_button.isEnabled())
        self.assertTrue(self.service.load().value.enabled)
        self.assertFalse(self.window._background_surface.background_active)
        self.window.background_controller.reload()
        self.assertTrue(self.controls.enabled_switch.isChecked())
        self.upload(still_background_bytes())
        self.assertTrue(self.controls.enabled_switch.isEnabled())
        self.assertTrue(self.window._background_surface.background_active)
        self.controls.enabled_switch.setChecked(True)
        self.assertTrue(self.window._background_surface.background_active)
        self.controls.opacity_slider.setValue(70)
        self.assertTrue(wait_for_condition(lambda: self.service.load().value.opacity == 70))
        state = self.service.load().value
        self.assertTrue(state.enabled)
        self.assertEqual(state.opacity, 70)
        self.window.background_controller.reload()
        self.assertEqual(self.controls.opacity_label.text(), "70%")
        self.assertEqual(self.controls.image_label.text(), "PNG | 1280 x 720")
        self.controls.enabled_switch.setChecked(False)
        self.assertTrue(self.controls.options_widget.isHidden())
        self.assertFalse(self.window._background_surface.background_active)
        self.assertIsNotNone(self.service.load().value.image)

    def test_animation_and_explicit_removal(self):
        self.upload(animated_background_bytes())
        self.controls.enabled_switch.setChecked(True)
        self.assertTrue(self.window._background_surface._state.image.animated)
        with patch("worklogger.presentation.settings.sections.background.QMessageBox.question",
                   return_value=QMessageBox.StandardButton.No):
            self.controls.remove_button.click()
        self.assertIsNotNone(self.service.load().value.image)
        with patch("worklogger.presentation.settings.sections.background.QMessageBox.question",
                   return_value=QMessageBox.StandardButton.Yes):
            self.controls.remove_button.click()
        self.assertIsNone(self.service.load().value.image)
        self.assertTrue(self.controls.enabled_switch.isEnabled())
        self.assertTrue(self.controls.enabled_switch.isChecked())
        self.assertFalse(self.controls.options_widget.isHidden())
        self.assertTrue(self.controls.upload_button.isEnabled())
        self.assertFalse(self.window._background_surface.background_active)

    def test_invalid_upload_retains_previous_media_and_reports_error(self):
        self.upload(still_background_bytes())
        self.controls.enabled_switch.setChecked(True)
        before = self.service.load().value
        self.upload(b"invalid")
        self.assertEqual(self.service.load().value, before)
        self.assertTrue(self.window._background_surface.background_active)
        self.assertFalse(self.controls.status_label.isHidden())
        self.assertTrue(self.controls.enabled_switch.isChecked())
        self.assertTrue(self.controls.upload_button.isEnabled())

    def test_cancelled_picker_does_not_change_preferences(self):
        self.controls.enabled_switch.setChecked(True)
        with patch("worklogger.presentation.settings.sections.background.QFileDialog.getOpenFileName",
                   return_value=("", "")):
            self.controls.upload_button.click()
        self.assertIsNone(self.service.load().value.image)
        self.assertFalse(self.window.background_controller.is_busy)

    def test_processing_state_blocks_duplicates_and_recovers_after_completion(self):
        class DeferredRunner:
            def submit(self, name, operation, *, on_complete):
                self.operation, self.complete = operation, on_complete
                return JobHandle(name, lambda: None)

        runner = DeferredRunner()
        self.controls.enabled_switch.setChecked(True)
        self.window.background_controller._runner = runner
        self.upload(still_background_bytes())
        self.assertTrue(self.window.background_controller.is_busy)
        self.assertFalse(self.controls.upload_button.isEnabled())
        self.assertFalse(self.controls.status_label.isHidden())
        self.assertFalse(self.window.background_controller.reload())
        runner.complete(runner.operation(CancellationToken()))
        self.assertTrue(self.controls.upload_button.isEnabled())
        self.assertTrue(self.controls.enabled_switch.isEnabled())
        self.assertTrue(self.controls.status_label.isHidden())

        self.controls.opacity_slider.setValue(60)
        self.controls.opacity_slider.setValue(70)
        self.assertTrue(self.window.background_controller.clear())
        self.assertFalse(self.window.background_controller.reload())
        self.assertFalse(self.controls.upload_button.isEnabled())
        self.assertFalse(self.controls.status_label.isHidden())
        runner.complete(runner.operation(CancellationToken()))
        runner.complete(runner.operation(CancellationToken()))
        self.assertEqual(self.service.load().value.opacity, 70)
        self.assertIsNotNone(self.service.load().value.image)
        runner.complete(runner.operation(CancellationToken()))
        self.assertIsNone(self.service.load().value.image)
        self.assertEqual(self.service.load().value.opacity, 70)
        self.assertFalse(self.window.background_controller.is_busy)
        self.assertTrue(self.controls.upload_button.isEnabled())
        self.assertTrue(self.controls.status_label.isHidden())

    def test_opacity_saves_keep_controls_stable_and_preserve_the_latest_selection(self):
        class DeferredRunner:
            def __init__(self):
                self.requests = []

            def submit(self, name, operation, *, on_complete):
                self.requests.append((operation, on_complete))
                return JobHandle(name, lambda: None)

            def finish(self, index):
                operation, complete = self.requests[index]
                complete(operation(CancellationToken()))

        self.upload(still_background_bytes())
        runner = DeferredRunner()
        controller = self.window.background_controller
        controller._runner = runner
        self.window.open_settings()
        self.window.show()
        self.app.processEvents()
        controls = self.controls
        previous_geometry = controls.geometry()
        with patch("worklogger.presentation.shell.background_controller.prepare_background") as decode:
            controls.opacity_slider.setSliderDown(True)
            controls.opacity_slider.setSliderPosition(43)
            self.assertEqual(len(runner.requests), 0)
            controls.opacity_slider.setSliderDown(False)
            self.assertTrue(controller.is_busy)
            for button in (controls.upload_button, controls.remove_button, controls.enabled_switch, controls.opacity_slider):
                self.assertTrue(button.isEnabled())
            self.assertTrue(controls.status_label.isHidden())
            self.app.processEvents()
            self.assertEqual(controls.geometry(), previous_geometry)
            controls.opacity_slider.setValue(65)
            controls.opacity_slider.setValue(70)
            self.assertEqual(len(runner.requests), 1)
            runner.finish(0)
            self.assertEqual(len(runner.requests), 2)
            self.assertEqual(controls.opacity_slider.value(), 70)
            controls.opacity_slider.setSliderDown(True)
            controls.opacity_slider.setSliderPosition(83)
            runner.finish(1)
            self.assertEqual(controls.opacity_slider.sliderPosition(), 83)
            controls.opacity_slider.setSliderDown(False)
            runner.finish(2)
            self.assertEqual(self.service.load().value.opacity, 83)
            self.assertEqual(controls.opacity_label.text(), "83%")
            self.assertFalse(controller.is_busy)
            self.assertTrue(controls.status_label.isHidden())
            self.app.processEvents()
            self.assertEqual(controls.geometry(), previous_geometry)
            decode.assert_not_called()
        controls.opacity_slider.setValue(60)
        runner.requests[3][1](Result.failure(InfrastructureError("background_storage_failed", "background_storage_failed")))
        self.assertEqual(controls.opacity_slider.value(), 83)
        self.assertTrue(controls.opacity_slider.isEnabled())
        self.assertFalse(controls.status_label.isHidden())
