"""Nonmodal first-use guidance preserves the current editor until an explicit action."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget

from tests.presentation.qt_support import dispose_test_windows
from worklogger.domain.shared.result import Result
from worklogger.presentation.job_runner import ImmediateJobRunner
from worklogger.presentation.shell.getting_started import GettingStartedController


class EntryPanel(QWidget):
    busy_changed = Signal(bool)
    is_busy = True


class GettingStartedPresentationTests(unittest.TestCase):
    def test_guidance_waits_for_the_editor_and_can_be_dismissed_and_reopened(self):
        app = QApplication.instance() or QApplication([])
        self.addCleanup(dispose_test_windows)
        window = QWidget()
        window.getting_started_layout = QVBoxLayout(window)
        window.entry_panel = EntryPanel()
        window.getting_started_layout.addWidget(window.entry_panel)
        window.help_button = QPushButton()
        actions = []
        window.new_record = lambda: actions.append("record") or True
        window._set_error = lambda error: self.fail(str(error))
        class Service:
            def pending(self):
                return Result.success(True)
            def dismiss(self):
                actions.append("dismiss")
                return Result.success(None)
        controller = GettingStartedController(window, Service(), job_runner=ImmediateJobRunner())
        window.show()
        app.processEvents()
        self.assertTrue(controller.panel.isHidden())
        controller._load()
        self.assertTrue(controller.panel.isHidden())
        window.entry_panel.is_busy = False
        window.entry_panel.busy_changed.emit(False)
        self.assertFalse(controller.panel.isHidden())
        self.assertEqual(actions, [])
        controller.panel.dismiss_button.click()
        self.assertTrue(controller.panel.isHidden())
        window.help_button.click()
        self.assertFalse(controller.panel.isHidden())
        controller.panel.record_button.click()
        self.assertEqual(actions, ["dismiss", "record", "dismiss"])
        self.assertTrue(controller.panel.isHidden())
        window.close()
