"""Release account-scoped desktop resources before application teardown."""

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QProgressDialog, QWidget
from shiboken6 import isValid
from worklogger.infrastructure.i18n import _


def dispose_runtime(runtime) -> None:
    try:
        runner = getattr(runtime, "job_runner", None)
        if runner is not None:
            finished = runner.shutdown(wait=True)
            if finished is False:
                progress = QProgressDialog(_("Stopping background tasks..."), "", 0, 0)
                progress.setCancelButton(None)
                progress.setWindowModality(Qt.WindowModality.ApplicationModal)
                progress.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
                progress.setMinimumDuration(0)
                progress.show()
                try:
                    # Keep account resources alive until cancelled work has actually stopped.
                    while runner.shutdown(wait=True, timeout_ms=250) is False:
                        pass
                finally:
                    progress.close()
                    progress.deleteLater()
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
