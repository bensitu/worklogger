"""Release account-scoped desktop resources before application teardown."""

import os
from time import monotonic

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid
from worklogger.presentation.widgets.shutdown_progress import BackgroundTaskShutdownDialog


def stop_background_tasks(runner, *, force_exit=None) -> None:
    deadline = monotonic() + 15
    finished = runner.shutdown(wait=True)
    if finished is False:
        progress = BackgroundTaskShutdownDialog()
        def force_quit():
            if runner.shutdown(wait=True, timeout_ms=0) is False:
                (force_exit or os._exit)(1)
        progress.force_quit_requested.connect(force_quit)
        progress.show()
        try:
            # Keep account resources alive until cancelled work has actually stopped.
            while runner.shutdown(wait=True, timeout_ms=250) is False:
                if monotonic() >= deadline:
                    progress.allow_force_quit()
                QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 25)
        finally:
            progress.hide()
            progress.deleteLater()


def dispose_runtime(runtime) -> None:
    try:
        runner = getattr(runtime, "job_runner", None)
        if runner is not None:
            stop_background_tasks(runner)
    finally:
        try:
            inference = getattr(runtime, "local_inference", None)
            if inference is not None:
                inference.close()
        finally:
            window = runtime.window
            if isinstance(window, QWidget) and isValid(window):
                window.deleteLater()
                QCoreApplication.sendPostedEvents(window, QEvent.Type.DeferredDelete)
