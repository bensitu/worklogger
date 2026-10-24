"""Timed removal of application-owned sensitive clipboard text."""

from hashlib import sha256
import sys

from PySide6.QtCore import QMimeData, QTimer
from PySide6.QtWidgets import QApplication


def copy_sensitive_text(text: str, *, timeout_ms: int = 60_000) -> None:
    application = QApplication.instance()
    clipboard = application.clipboard()
    timer = application.findChild(QTimer, "credential_clipboard_timer")
    if timer is None:
        timer = QTimer(application)
        timer.setObjectName("credential_clipboard_timer")
        timer.setSingleShot(True)

        def clear_owned_text():
            expected = timer.property("content_digest")
            timer.setProperty("content_digest", None)
            if expected == sha256(clipboard.text().encode("utf-8")).hexdigest():
                clipboard.clear()

        timer.timeout.connect(clear_owned_text)
        application.aboutToQuit.connect(clear_owned_text)
    content = QMimeData()
    if sys.platform == "win32":
        for name in ("ExcludeClipboardContentFromMonitorProcessing", "CanIncludeInClipboardHistory", "CanUploadToCloudClipboard"):
            content.setData(f'application/x-qt-windows-mime;value="{name}"', b"\0\0\0\0")
    content.setText(text)
    clipboard.setMimeData(content)
    timer.setProperty("content_digest", sha256(text.encode("utf-8")).hexdigest())
    timer.start(timeout_ms)
