"""Dispose owned test windows before another test reapplies application styles."""

import gc
from time import monotonic
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


def wait_for_condition(predicate, timeout_ms=3000):
    deadline = monotonic() + timeout_ms / 1000
    while not predicate():
        if monotonic() >= deadline:
            return False
        QTest.qWait(10)
    return True


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
