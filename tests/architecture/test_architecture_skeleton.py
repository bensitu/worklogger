from __future__ import annotations

from datetime import date
import unittest

from worklogger.app.container import AppContainer, DependencyNotRegisteredError
from worklogger.app.event_bus import EventBus, WorkLogSaved
from worklogger.app.job_runner import CancellationToken
from worklogger.app.ports import AIGateway, BackupService, KeyStore, LocalModelManager
from worklogger.config.feature_flags import FeatureFlag, FeatureFlags
from worklogger.domain.auth.repositories import IdentityRepository, UserRepository
from worklogger.domain.calendar.repositories import CalendarEventRepository
from worklogger.domain.quicklog.repositories import QuickLogRepository
from worklogger.domain.reporting.repositories import ReportRepository
from worklogger.domain.settings.repositories import SettingsRepository
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.repositories import WorkLogRepository


class ArchitectureSkeletonTests(unittest.TestCase):
    def test_result_success_and_failure_contract(self) -> None:
        success = Result.success("ok")
        self.assertTrue(success.ok)
        self.assertEqual(success.value, "ok")
        self.assertIsNone(success.error)

        error = ValidationError("invalid_time", "Invalid time range")
        failure = Result.failure(error)
        self.assertFalse(failure.ok)
        self.assertIs(failure.error, error)

        with self.assertRaises(ValueError):
            Result(ok=True, error=error)
        with self.assertRaises(ValueError):
            Result(ok=False)

    def test_container_resolves_registered_instances_and_factories(self) -> None:
        container = AppContainer()
        token = object()
        container.register_instance(token, "stored")
        self.assertEqual(container.resolve(token), "stored")

        other_token = object()
        calls: list[int] = []
        container.register_factory(
            other_token,
            lambda _container: calls.append(1) or {"value": len(calls)},
            singleton=True,
        )
        first = container.resolve(other_token)
        second = container.resolve(other_token)
        self.assertIs(first, second)
        self.assertEqual(first, {"value": 1})

        with self.assertRaises(DependencyNotRegisteredError):
            container.resolve(object())

    def test_event_bus_publish_and_unsubscribe(self) -> None:
        bus = EventBus()
        received: list[WorkLogSaved] = []
        unsubscribe = bus.subscribe(WorkLogSaved, received.append)
        event = WorkLogSaved(user_id=1, day=date(2026, 5, 13))

        bus.publish(event)
        unsubscribe()
        bus.publish(event)

        self.assertEqual(received, [event])

    def test_cancellation_token_is_cooperative(self) -> None:
        token = CancellationToken()
        self.assertFalse(token.is_cancelled())
        token.cancel()
        self.assertTrue(token.is_cancelled())

    def test_feature_flags_default_policy_matches_skeleton_requirements(self) -> None:
        flags = FeatureFlags()
        self.assertTrue(flags.is_enabled(FeatureFlag.AI))
        self.assertTrue(flags.is_enabled(FeatureFlag.LOCAL_MODELS))
        self.assertFalse(flags.is_enabled(FeatureFlag.GOOGLE_IDENTITY))
        self.assertFalse(flags.is_enabled(FeatureFlag.MICROSOFT_IDENTITY))
        self.assertTrue(flags.is_enabled(FeatureFlag.ANALYTICS_PDF_NARRATIVE))
        self.assertTrue(flags.is_enabled(FeatureFlag.UPDATE_CHECK))

    def test_feature_flags_can_be_loaded_from_environment_mapping(self) -> None:
        flags = FeatureFlags.from_env(
            {
                "WORKLOGGER_FEATURE_AI": "1",
                "WORKLOGGER_FEATURE_LOCAL_MODELS": "0",
                "WORKLOGGER_FEATURE_GOOGLE_IDENTITY": "yes",
                "WORKLOGGER_FEATURE_MICROSOFT_IDENTITY": "true",
                "WORKLOGGER_FEATURE_ANALYTICS_PDF_NARRATIVE": "on",
                "WORKLOGGER_FEATURE_UPDATE_CHECK": "0",
            }
        )
        self.assertTrue(flags.enable_ai)
        self.assertFalse(flags.enable_local_models)
        self.assertTrue(flags.enable_google_identity)
        self.assertTrue(flags.enable_microsoft_identity)
        self.assertTrue(flags.enable_analytics_pdf_narrative)
        self.assertFalse(flags.enable_update_check)

    def test_required_protocols_are_importable(self) -> None:
        protocols = (
            WorkLogRepository,
            UserRepository,
            IdentityRepository,
            QuickLogRepository,
            ReportRepository,
            CalendarEventRepository,
            SettingsRepository,
            AIGateway,
            KeyStore,
            BackupService,
            LocalModelManager,
        )
        self.assertTrue(all(protocol.__name__ for protocol in protocols))

    def test_skeleton_entry_point_smoke_imports(self) -> None:
        from worklogger.main import main

        self.assertEqual(main(["--smoke-import"]), 0)


if __name__ == "__main__":
    unittest.main()
