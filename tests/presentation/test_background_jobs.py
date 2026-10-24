from __future__ import annotations

import os
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result
from worklogger.presentation.job_runner import ImmediateJobRunner, QtJobRunner


def _app() -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        return existing
    return QApplication([])


class BackgroundJobTests(unittest.TestCase):
    def test_forced_shutdown_requires_a_delayed_option_and_explicit_confirmation(self):
        from worklogger.presentation.widgets.shutdown_progress import BackgroundTaskShutdownDialog
        dialog = BackgroundTaskShutdownDialog()
        self.addCleanup(dialog.deleteLater)
        requests = []
        dialog.force_quit_requested.connect(lambda: requests.append(True))
        dialog.force_button.click()
        self.assertEqual(requests, [])
        dialog.allow_force_quit()
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.No):
            dialog.force_button.click()
        self.assertEqual(requests, [])
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Yes):
            dialog.force_button.click()
        self.assertEqual(requests, [True])

    def test_shutdown_processes_user_events_without_releasing_running_work(self):
        from PySide6.QtCore import QTimer
        from worklogger.composition.lifecycle import stop_background_tasks
        from worklogger.presentation.widgets.shutdown_progress import BackgroundTaskShutdownDialog
        class Runner:
            active = True
            def shutdown(self, **_kwargs):
                return not self.active
        runner, exits = Runner(), []
        def progress():
            dialog = BackgroundTaskShutdownDialog()
            QTimer.singleShot(0, dialog.force_button.click)
            return dialog
        def terminate(code):
            exits.append(code)
            runner.active = False
        with patch("worklogger.composition.lifecycle.BackgroundTaskShutdownDialog", side_effect=progress), \
                patch("worklogger.composition.lifecycle.monotonic", side_effect=[0, 16]), \
                patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Yes):
            stop_background_tasks(runner, force_exit=terminate)
        self.assertEqual(exits, [1])

    def test_render_and_long_tasks_do_not_block_short_work_or_shutdown_events(self):
        from PySide6.QtCore import QTimer
        runner = QtJobRunner()
        started, release = threading.Event(), threading.Event()
        completed, responsive = [], []
        runner._pool.setMaxThreadCount(1)
        runner._long_pool.setMaxThreadCount(1)
        runner._render_pool.setMaxThreadCount(1)
        render_started = threading.Event()
        def slow(_token):
            started.set()
            release.wait(3)
        runner.submit("local_model_download", slow)
        runner.submit("glass_background", lambda _token: (render_started.set(), release.wait(3)))
        self.assertTrue(started.wait(3))
        self.assertTrue(render_started.wait(3))
        try:
            runner.submit("load_calendar_overview", lambda _token: 42, on_complete=completed.append)
            deadline = time.monotonic() + 3
            while not completed and time.monotonic() < deadline:
                self._app.processEvents()
                time.sleep(0.001)
            self.assertEqual(completed[0].value, 42)
            QTimer.singleShot(0, lambda: responsive.append(True))
            self.assertFalse(runner.shutdown(wait=True, timeout_ms=20))
            self.assertTrue(responsive)
        finally:
            release.set()
            self.assertTrue(runner.shutdown(wait=True))

    def test_processing_completion_ignores_results_replaced_by_finished_signal(self):
        from worklogger.app.job_runner import JobHandle
        from worklogger.presentation.processing import TextProcessingTask

        class DeferredRunner:
            def __init__(self):
                self.callbacks = []
            def submit(self, name, work, *, on_complete):
                self.callbacks.append(on_complete)
                return JobHandle(name, lambda: None)

        runner = DeferredRunner()
        task = TextProcessingTask(job_runner=runner)
        self.addCleanup(task.deleteLater)
        results, restarted = [], []

        def restart():
            if not restarted:
                restarted.append(True)
                task.run("second", lambda _token: "Second", on_complete=results.append)

        task.finished.connect(restart)
        task.run("first", lambda _token: "First", on_complete=results.append)
        runner.callbacks[0](Result.success("First"))
        self.assertTrue(task.is_running)
        self.assertEqual(results, [])
        runner.callbacks[1](Result.success("Second"))
        self.assertEqual(results[0].value, "Second")
        self.assertFalse(task.is_running)

    def test_owned_completion_ignores_a_deleted_widget(self):
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QWidget
        from worklogger.presentation.job_runner import owned_callback

        owner = QWidget()
        results = []
        complete = owned_callback(owner, results.append)
        first = Result.success("Current result")
        complete(first)
        self.assertEqual(results, [first])
        owner.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        complete(Result.success("Late result"))
        self.assertEqual(results, [first])

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
