from __future__ import annotations

import unittest

from worklogger.app.queries.update_queries import CheckForUpdatesQuery
from worklogger.app.use_cases.updates import CheckForUpdatesHandler
from worklogger.domain.shared.result import Result


class FakeChecker:
    def __init__(self, latest: str | None) -> None:
        self.latest = latest

    def check_latest_version(self, current_version: str) -> Result[str | None]:
        return Result.success(self.latest)


class UpdateUseCaseTests(unittest.TestCase):
    def test_update_handler_reports_available_and_latest_states(self) -> None:
        available = CheckForUpdatesHandler(FakeChecker("4.0.1")).handle(
            CheckForUpdatesQuery("4.0.0")
        )
        current = CheckForUpdatesHandler(FakeChecker(None)).handle(
            CheckForUpdatesQuery("4.0.1")
        )

        self.assertTrue(available.ok, available.error)
        assert available.value is not None
        self.assertTrue(available.value.update_available)
        self.assertEqual(available.value.latest_version, "4.0.1")
        self.assertTrue(current.ok, current.error)
        assert current.value is not None
        self.assertFalse(current.value.update_available)


if __name__ == "__main__":
    unittest.main()
