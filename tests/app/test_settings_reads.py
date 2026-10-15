"""Shared preference-read defaults, batching, and error propagation."""

import unittest
from unittest.mock import Mock

from worklogger.app.settings import read_setting_values
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result


class SettingsReadTests(unittest.TestCase):
    def test_batch_and_individual_reads_apply_the_same_defaults_and_preserve_empty_values(self):
        defaults = {"language": "en_US", "theme": "blue", "region": "JP", "optional": None}
        values = {"language": "ja_JP", "theme": None, "region": ""}
        expected = {"language": "ja_JP", "theme": "blue", "region": "", "optional": None}
        reader = Mock()
        reader.handle.side_effect = lambda query: Result.success(values.get(query.key))
        for batch in (None, Result.success(None), Result.success(values)):
            reader.reset_mock()
            reader.get_many.return_value = batch
            result = read_setting_values(reader, 7, defaults)
            self.assertTrue(result.ok)
            self.assertEqual(result.value, expected)
            reader.get_many.assert_called_once_with(7, tuple(defaults))
            self.assertEqual(reader.handle.call_count, 0 if batch is not None and batch.value is not None else 4)

    def test_failed_batch_does_not_fall_back_or_expose_partial_values(self):
        error = InfrastructureError("settings_load_failed", "settings_load_failed")
        reader = Mock()
        reader.get_many.return_value = Result.failure(error)
        result = read_setting_values(reader, 7, {"theme": "blue"})
        self.assertIs(result.error, error)
        reader.handle.assert_not_called()
        reader.get_many.side_effect = OSError("Unavailable settings")
        self.assertEqual(read_setting_values(reader, 7, {"theme": "blue"},
                                             error_code="ai_context_settings_failed").error.code,
                         "ai_context_settings_failed")
