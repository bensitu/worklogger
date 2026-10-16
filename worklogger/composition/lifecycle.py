"""Release account-scoped desktop resources before application teardown."""

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid


def dispose_runtime(runtime) -> None:
    try:
        runner = getattr(runtime, "job_runner", None)
        if runner is not None:
            runner.shutdown(wait=True)
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
