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
    def test_processing_requests_cancel_and_ignore_late_or_replaced_results(self):
        from worklogger.presentation.processing import TextProcessingTask
        from worklogger.app.job_runner import JobHandle
        class DeferredRunner:
            def __init__(self):
                self.callbacks = []
                self.cancelled = []
            def submit(self, name, work, *, on_complete):
                self.callbacks.append(on_complete)
                return JobHandle(name, lambda: self.cancelled.append(name))
        runner = DeferredRunner()
        task = TextProcessingTask(job_runner=runner)
        completed, changes = [], []
        task.started.connect(lambda: changes.append("started"))
        task.finished.connect(lambda: changes.append("finished"))
        self.assertTrue(task.run("first", lambda token: "first", on_complete=completed.append))
        self.assertFalse(task.run("duplicate", lambda token: "duplicate", on_complete=completed.append))
        task.cancel()
        self.assertFalse(task.is_running)
        self.assertEqual(runner.cancelled, ["first"])
        self.assertEqual(completed[0].error.code, "ai_rewrite_cancelled")
        self.assertTrue(task.run("second", lambda token: "second", on_complete=completed.append))
        runner.callbacks[0](Result.success("Late first result"))
        self.assertTrue(task.is_running)
        self.assertEqual(len(completed), 1)
        runner.callbacks[1](Result.success("Second result"))
        self.assertEqual(completed[1].value, "Second result")
        self.assertEqual(changes, ["started", "finished", "started", "finished"])

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

    def test_shutdown_cancels_work_and_suppresses_callbacks(self) -> None:
        runner = QtJobRunner()
        started = threading.Event()
        cancelled = threading.Event()
        completed = []

        def job(token):
            started.set()
            while not token.is_cancelled():
                time.sleep(0.001)
            cancelled.set()

        runner.submit("operation", job, on_complete=completed.append)
        self.assertTrue(started.wait(3))
        runner.shutdown(wait=True)
        self._app.processEvents()
        self.assertTrue(cancelled.is_set())
        self.assertEqual(completed, [])
        with self.assertRaises(RuntimeError):
            runner.submit("operation", job)


if __name__ == "__main__":
    unittest.main()
