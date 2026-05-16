from __future__ import annotations

import os
import threading
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result
from worklogger.presentation.job_runner import ImmediateJobRunner, QtJobRunner


def _app() -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        return existing
    return QApplication([])


class BackgroundJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = _app()

    def test_qt_job_runner_runs_job_off_ui_thread_and_completes_on_ui_thread(self) -> None:
        runner = QtJobRunner()
        ui_thread_id = threading.get_ident()
        worker_thread_ids: list[int] = []
        completed: list[tuple[Result[object], int]] = []

        runner.submit(
            "demo",
            lambda _token: worker_thread_ids.append(threading.get_ident()) or 42,
            on_complete=lambda result: completed.append(
                (result, threading.get_ident())
            ),
        )

        deadline = time.monotonic() + 3
        while not completed and time.monotonic() < deadline:
            self._app.processEvents()
            time.sleep(0.01)

        self.assertTrue(completed)
        self.assertTrue(completed[0][0].ok)
        self.assertEqual(completed[0][0].value, 42)
        self.assertNotEqual(worker_thread_ids[0], ui_thread_id)
        self.assertEqual(completed[0][1], ui_thread_id)

    def test_immediate_job_runner_flattens_result_return_values(self) -> None:
        runner = ImmediateJobRunner()
        completed: list[Result[object]] = []

        runner.submit(
            "validation",
            lambda _token: Result.failure(
                ValidationError("invalid", "invalid")
            ),
            on_complete=completed.append,
        )

        self.assertEqual(completed[0].error.code if completed[0].error else "", "invalid")


if __name__ == "__main__":
    unittest.main()
