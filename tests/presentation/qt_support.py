"""Dispose owned test windows before another test reapplies application styles."""

import gc
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication


def dispose_test_windows():
    application = QApplication.instance()
    if application is None:
        return
    for widget in application.topLevelWidgets():
        if widget.parentWidget() is None:
            widget.hide()
            widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()
