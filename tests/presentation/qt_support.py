"""Bounded Qt event waiting and owned test-window cleanup."""

import gc
from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication


def wait_for_condition(predicate, timeout_ms=3000):
    if predicate():
        return True
    if timeout_ms <= 0:
        return False
    loop = QEventLoop()
    poll, deadline = QTimer(loop), QTimer(loop)
    errors = []

    def check():
        try:
            if predicate():
                loop.quit()
        except Exception as error:
            errors.append(error)
            loop.quit()

    poll.timeout.connect(check)
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    poll.start(10)
    deadline.start(timeout_ms)
    try:
        loop.exec()
    finally:
        poll.stop()
        deadline.stop()
        loop.deleteLater()
    if errors:
        raise errors[0]
    return bool(predicate())


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
