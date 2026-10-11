from __future__ import annotations

from datetime import date
import unittest

from worklogger.app.event_bus import EventBus, WorkLogSaved
from worklogger.app.job_runner import CancellationToken
from worklogger.config.feature_flags import FeatureFlag, FeatureFlags
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result


class ApplicationContractTests(unittest.TestCase):
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

    def test_feature_flags_have_expected_defaults(self) -> None:
        flags = FeatureFlags()
        self.assertTrue(flags.is_enabled(FeatureFlag.AI))
        self.assertTrue(flags.is_enabled(FeatureFlag.LOCAL_MODELS))
        self.assertTrue(flags.is_enabled(FeatureFlag.UPDATE_CHECK))

    def test_feature_flags_can_be_loaded_from_environment_mapping(self) -> None:
        flags = FeatureFlags.from_env(
            {
                "WORKLOGGER_FEATURE_AI": "1",
                "WORKLOGGER_FEATURE_LOCAL_MODELS": "0",
                "WORKLOGGER_FEATURE_UPDATE_CHECK": "0",
            }
        )
        self.assertTrue(flags.enable_ai)
        self.assertFalse(flags.enable_local_models)
        self.assertFalse(flags.enable_update_check)


if __name__ == "__main__":
    unittest.main()
