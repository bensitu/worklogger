"""Deployment flags fail closed and resolve independently of the working directory."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from worklogger.composition.desktop import _window_config_for_user
from worklogger.domain.auth.models import User
from worklogger.infrastructure.runtime_config import (
    CONFIG_FILENAME,
    DeploymentFeatures,
    RuntimeConfiguration,
    configuration_path,
    load_runtime_configuration,
)
from worklogger.presentation.shell.app_window import AppWindowConfig


class RuntimeConfigurationTests(unittest.TestCase):
    def test_configuration_cache_observes_replacements_and_deletion(self):
        self.path.write_text('{"features":{"ai":false}}', encoding="utf-8")
        first = load_runtime_configuration(self.path)
        self.assertIs(load_runtime_configuration(self.path), first)
        status = self.path.stat()
        self.path.write_text('{"features":{"ai":true }}', encoding="utf-8")
        with patch.object(Path, "stat", return_value=status):
            self.assertTrue(load_runtime_configuration(self.path).features.ai)
        replacement = self.path.with_suffix(".replacement")
        replacement.write_text('{"features":{"ai":false}}', encoding="utf-8")
        self.assertEqual(replacement.stat().st_size, self.path.stat().st_size)
        replacement.replace(self.path)
        self.assertFalse(load_runtime_configuration(self.path).features.ai)
        self.path.unlink()
        self.assertTrue(load_runtime_configuration(self.path).features.ai)

    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.path = self.directory / CONFIG_FILENAME

    def test_flags_are_strict_booleans_and_invalid_or_missing_files_fail_closed(self):
        self.assertTrue(load_runtime_configuration(self.path).valid)
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
                      '{"features":{"minimal_view":"true"}}', '{"features":[]}', '[]', 'invalid', ' ' * 65537,
                      '[' * 1500 + ']' * 1500):
            self.path.write_text(value, encoding="utf-8")
            with self.assertLogs("worklogger.infrastructure.runtime_config", level="WARNING"):
                self.assertFalse(load_runtime_configuration(self.path).valid)
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

    def test_service_features_default_enabled_and_invalid_values_disable_them(self):
        for name in ("ai", "cloud_backup", "self_registration", "oidc"):
            self.assertTrue(getattr(load_runtime_configuration(self.path).features, name))
        for name in ("ai", "cloud_backup", "self_registration", "oidc"):
            for features, expected in (({}, True), ({name: True}, True), ({name: False}, False)):
                self.path.write_text(json.dumps({"features": features}), encoding="utf-8")
                flags = load_runtime_configuration(self.path).features
                self.assertEqual(getattr(flags, name), expected)
                self.assertTrue(getattr(flags, "cloud_backup" if name == "ai" else "ai"))
            for candidate in ("false", 0, None):
                self.path.write_text(json.dumps({"features": {name: candidate}}), encoding="utf-8")
                with self.assertLogs("worklogger.infrastructure.runtime_config", level="WARNING"):
                    self.assertFalse(getattr(load_runtime_configuration(self.path).features, name))
        self.path.write_text('{invalid', encoding="utf-8")
        with self.assertLogs("worklogger.infrastructure.runtime_config", level="WARNING"):
            flags = load_runtime_configuration(self.path).features
            self.assertFalse(flags.ai)
            self.assertFalse(flags.cloud_backup)
            self.assertFalse(flags.self_registration)
            self.assertFalse(flags.oidc)

    def test_cloud_backup_delay_accepts_bounded_integer_seconds_and_defaults_when_missing(self):
        self.assertEqual(load_runtime_configuration(self.path).cloud_backup.startup_delay_seconds, 300)
        for options, expected in (({}, 300), ({"cloud_backup": {}}, 300),
                                  *(({"cloud_backup": {"startup_delay_seconds": delay}}, delay)
                                    for delay in (0, 1, 17, 300, 86400))):
            with self.subTest(options=options):
                self.path.write_text(json.dumps(options), encoding="utf-8")
                self.assertEqual(load_runtime_configuration(self.path).cloud_backup.startup_delay_seconds, expected)

    def test_invalid_cloud_backup_delay_preserves_other_valid_configuration(self):
        for options in (None, [], True, "300", *({"startup_delay_seconds": delay}
                         for delay in (-1, 86401, True, None, "300", 1.5, 300.0, 10**100))):
            with self.subTest(options=options):
                self.path.write_text(json.dumps({"features": {"minimal_view": True}, "cloud_backup": options}), encoding="utf-8")
                with self.assertLogs("worklogger.infrastructure.runtime_config", level="WARNING"):
                    configuration = load_runtime_configuration(self.path)
                self.assertEqual(configuration.cloud_backup.startup_delay_seconds, 300)
                self.assertTrue(configuration.features.minimal_view)

    def test_cloud_backup_schedule_options_validate_independently_and_reject_inverted_retry_bounds(self):
        options = {"startup_delay_seconds": 17, "check_interval_seconds": 11,
                   "retry_initial_seconds": 7, "retry_max_seconds": 21}
        self.path.write_text(json.dumps({"cloud_backup": options}), encoding="utf-8")
        backup = load_runtime_configuration(self.path).cloud_backup
        self.assertEqual((backup.startup_delay_seconds, backup.check_interval_seconds,
                          backup.retry_initial_seconds, backup.retry_max_seconds), (17, 11, 7, 21))
        for key, invalid, default in (("check_interval_seconds", True, 60), ("check_interval_seconds", 0, 60),
                                      ("retry_initial_seconds", "7", 300), ("retry_max_seconds", 86401, 3600)):
            with self.subTest(key=key, invalid=invalid):
                self.path.write_text(json.dumps({"cloud_backup": {**options, key: invalid}}), encoding="utf-8")
                with self.assertLogs("worklogger.infrastructure.runtime_config", level="WARNING"):
                    backup = load_runtime_configuration(self.path).cloud_backup
                self.assertEqual(getattr(backup, key), default)
                self.assertEqual(backup.startup_delay_seconds, 17)
        self.path.write_text(json.dumps({"cloud_backup": {**options, "retry_initial_seconds": 60}}), encoding="utf-8")
        with self.assertLogs("worklogger.infrastructure.runtime_config", level="WARNING"):
            backup = load_runtime_configuration(self.path).cloud_backup
        self.assertEqual((backup.retry_initial_seconds, backup.retry_max_seconds), (300, 3600))
        self.assertEqual(backup.check_interval_seconds, 11)

    def test_external_profiles_validate_capabilities_without_changing_feature_flags(self):
        profile = {"base_url": "https://example.com/v1/", "model": "sample-model",
                   "temperature": 0.2, "max_output_tokens": 2048,
                   "token_limit_parameter": "max_completion_tokens"}
        def load(profiles):
            self.path.write_text(json.dumps({"features": {"minimal_view": True},
                                            "external_model_profiles": profiles}), encoding="utf-8")
            return load_runtime_configuration(self.path)
        configuration = load([profile])
        parsed = configuration.external_model_profiles[0]
        self.assertEqual((parsed.base_url, parsed.model), ("https://example.com/v1", "sample-model"))
        self.assertEqual(parsed.options.payload(), {"temperature": 0.2, "max_completion_tokens": 2048})
        for key, value in (("temperature", True), ("temperature", float("nan")), ("temperature", 10**400),
                           ("max_output_tokens", 0), ("max_output_tokens", True), ("max_output_tokens", 1.5),
                           ("token_limit_parameter", "model"), ("model", ""), ("base_url", "http://example.com"),
                           ("base_url", None), ("api_key", "synthetic")):
            with self.subTest(key=key, value=value), self.assertLogs("worklogger.infrastructure.runtime_config", level="WARNING"):
                configuration = load([dict(profile, **{key: value})])
                self.assertTrue(configuration.features.minimal_view)
                self.assertEqual(configuration.external_model_profiles, ())
        for profiles in ({}, [profile, profile], [profile] * 129):
            with self.assertLogs("worklogger.infrastructure.runtime_config", level="WARNING"):
                self.assertEqual(load(profiles).external_model_profiles, ())

    def test_processing_timeouts_validate_per_field_and_reach_ai_requests(self):
        from worklogger.app.commands.ai_commands import RewriteTextCommand, SendAiChatMessageCommand
        from worklogger.composition.context import build_runtime_handlers
        from worklogger.domain.shared.result import Result

        options = {"features": {"minimal_view": True},
                   "ai": {"rewrite_timeout_seconds": 47, "chat_timeout_seconds": 89, "connection_test_timeout_seconds": 7},
                   "local_models": {"download_timeout_seconds": 91, "catalog_timeout_seconds": 23}}
        self.path.write_text(json.dumps(options), encoding="utf-8")
        configuration = load_runtime_configuration(self.path)
        gateway = Mock()
        gateway.generate.return_value = Result.success(SimpleNamespace(text="Synthetic reply"))
        with patch("worklogger.composition.context.load_runtime_configuration", return_value=configuration), \
                patch("worklogger.composition.context.AccountAIGateway", return_value=gateway):
            handlers = build_runtime_handlers(Mock(), holiday_country="JP", user_id=1, database_path=self.directory / "worklog.db")
        self.assertTrue(handlers.rewrite_handler.handle(RewriteTextCommand(1, "Synthetic content")).ok)
        self.assertTrue(handlers.ai_chat_handler.handle(SendAiChatMessageCommand(1, "Synthetic message")).ok)
        self.assertEqual([call.args[0].timeout_seconds for call in gateway.generate.call_args_list], [47, 89])
        for section, key, invalid, default in (
            ("ai", "rewrite_timeout_seconds", True, 180), ("ai", "chat_timeout_seconds", 0, 180),
            ("ai", "connection_test_timeout_seconds", 301, 30),
            ("local_models", "download_timeout_seconds", "91", 30),
            ("local_models", "catalog_timeout_seconds", 301, 15),
        ):
            with self.subTest(section=section, key=key):
                changed = {**options, section: {**options[section], key: invalid}}
                self.path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertLogs("worklogger.infrastructure.runtime_config", level="WARNING"):
                    parsed = load_runtime_configuration(self.path)
                self.assertEqual(getattr(getattr(parsed, section), key), default)
                self.assertTrue(parsed.features.minimal_view)

    def test_pagination_values_reach_search_services_and_validate_independently(self):
        from datetime import date
        from worklogger.composition.context import build_runtime_handlers
        from worklogger.composition.recording import build_time_entry_view_model
        from worklogger.composition.reporting import build_notes_workflow, build_reports_workflow
        from worklogger.domain.notes.models import NoteHistoryFilter
        from worklogger.domain.reporting.history import ReportHistoryFilter
        from worklogger.domain.worklog.search import EntryFilter

        options = {"notes_page_size": 61, "records_page_size": 23, "reports_page_size": 17}
        self.path.write_text(json.dumps({"pagination": options}), encoding="utf-8")
        configuration = load_runtime_configuration(self.path)
        repositories = Mock()
        repositories.settings.get.return_value = None
        with patch("worklogger.composition.context.load_runtime_configuration", return_value=configuration):
            handlers = build_runtime_handlers(repositories, holiday_country="JP")
        user = User(1, "sample")
        build_time_entry_view_model(user, repositories, handlers).search(EntryFilter(date.min, date.max))
        build_notes_workflow(user, repositories, handlers)._view_model.browse(NoteHistoryFilter())
        build_reports_workflow(user, repositories, handlers).view_model.browse_history(
            ReportHistoryFilter("daily", date.min, date.max))
        self.assertEqual(repositories.work_logs.search_entries.call_args.kwargs["limit"], 23)
        self.assertEqual(repositories.daily_notes.browse.call_args.args[1].limit, 61)
        self.assertEqual(repositories.reports.search_history.call_args.kwargs["limit"], 17)
        for key, invalid, default in (("notes_page_size", 101, 50), ("records_page_size", 251, 100),
                                      ("reports_page_size", True, 50), ("notes_page_size", 0, 50)):
            self.path.write_text(json.dumps({"pagination": {**options, key: invalid}}), encoding="utf-8")
            with self.assertLogs("worklogger.infrastructure.runtime_config", level="WARNING"):
                parsed = load_runtime_configuration(self.path).pagination
            self.assertEqual(getattr(parsed, key), default)
            for other in options.keys() - {key}:
                self.assertEqual(getattr(parsed, other), options[other])

    def test_deployment_flag_controls_window_availability_without_changing_account_preferences(self):
        user = User(id=1, username="sample", is_admin=False)
        for enabled in (True, False):
            configuration = RuntimeConfiguration(DeploymentFeatures(background_images=enabled))
            with patch("worklogger.infrastructure.runtime_config.load_runtime_configuration", return_value=configuration):
                self.assertEqual(_window_config_for_user(AppWindowConfig(), user).background_images_available, enabled)
                self.assertFalse(_window_config_for_user(AppWindowConfig(background_images_available=False), user).background_images_available)
