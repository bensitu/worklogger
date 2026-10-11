"""Deployment flags fail closed and resolve independently of the working directory."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from worklogger.bootstrap import _window_config_for_user
from worklogger.domain.auth.models import User
from worklogger.infrastructure.runtime_config import (
    CONFIG_FILENAME,
    FeatureFlags,
    RuntimeConfiguration,
    configuration_path,
    load_runtime_configuration,
)
from worklogger.presentation.shell.app_window import AppWindowConfig


class RuntimeConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.path = self.directory / CONFIG_FILENAME

    def test_flags_are_strict_booleans_and_invalid_or_missing_files_fail_closed(self):
        self.assertFalse(load_runtime_configuration(self.path).features.background_images)
        self.assertFalse(load_runtime_configuration(self.path).features.minimal_view)
        for enabled in (True, False):
            self.path.write_text(json.dumps({"features": {"background_images": enabled, "minimal_view": enabled}}), encoding="utf-8-sig")
            self.assertEqual(load_runtime_configuration(self.path).features.background_images, enabled)
            self.assertEqual(load_runtime_configuration(self.path).features.minimal_view, enabled)
        self.path.write_text('{"features":{"background_images":true}}', encoding="utf-8")
        self.assertTrue(load_runtime_configuration(self.path).features.background_images)
        self.assertFalse(load_runtime_configuration(self.path).features.minimal_view)
        for value in ('{"features":{"background_images":"true"}}', '{"features":{"minimal_view":1}}',
                      '{"features":{"minimal_view":"true"}}', '{"features":[]}', '[]', 'invalid', ' ' * 65537):
            self.path.write_text(value, encoding="utf-8")
            with self.assertLogs("worklogger.infrastructure.runtime_config", level="WARNING"):
                self.assertFalse(load_runtime_configuration(self.path).features.background_images)
                self.assertFalse(load_runtime_configuration(self.path).features.minimal_view)

    def test_source_and_frozen_paths_prioritize_an_explicit_adjacent_file(self):
        self.assertEqual(configuration_path(frozen=False, source_root=self.directory), self.path)
        executable = self.directory / "app" / "WorkLogger.exe"
        bundle = self.directory / "bundle"
        self.assertEqual(configuration_path(frozen=True, executable=executable, bundle_root=bundle), bundle / CONFIG_FILENAME)
        adjacent = executable.parent / CONFIG_FILENAME
        adjacent.parent.mkdir()
        adjacent.write_text("{}", encoding="utf-8")
        self.assertEqual(configuration_path(frozen=True, executable=executable, bundle_root=bundle), adjacent)

    def test_deployment_flag_controls_window_availability_without_changing_account_preferences(self):
        user = User(id=1, username="sample", is_admin=False)
        for enabled in (True, False):
            configuration = RuntimeConfiguration(FeatureFlags(background_images=enabled))
            with patch("worklogger.infrastructure.runtime_config.load_runtime_configuration", return_value=configuration):
                self.assertEqual(_window_config_for_user(AppWindowConfig(), user).background_images_available, enabled)
                self.assertFalse(_window_config_for_user(AppWindowConfig(background_images_available=False), user).background_images_available)
