"""Modal first-use guidance preserves drafts and restores recording focus."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace
from PySide6.QtCore import Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLineEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget

from tests.presentation.qt_support import dispose_test_windows
from worklogger.domain.shared.result import Result
from tests.job_runner import ImmediateJobRunner
from worklogger.presentation.shell.getting_started import GettingStartedController


class EntryPanel(QWidget):
    busy_changed = Signal(bool)
    dirty_changed = Signal(bool)
    is_busy = True
    is_dirty = False
    is_processing_text = False

    def __init__(self):
        super().__init__()
        self.view_model = SimpleNamespace(timer=None, restore_failed=False)
        self.start_input = QLineEdit("09:00")
        self.time_tabs = QTabWidget()
        self.time_tabs.addTab(QWidget(), "Manual")
        self.time_tabs.addTab(QWidget(), "Automatic")
        self.clock_in_button = QPushButton("Start")
        layout = QVBoxLayout(self)
        layout.addWidget(self.time_tabs)
        layout.addWidget(self.start_input)
        layout.addWidget(self.clock_in_button)


class GettingStartedPresentationTests(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.addCleanup(dispose_test_windows)
        self.window = QWidget()
        layout = QHBoxLayout(self.window)
        layout.addWidget(QPushButton("Calendar"), 1)
        self.window.entry_panel = EntryPanel()
        self.window.entry_panel.setFixedWidth(300)
        layout.addWidget(self.window.entry_panel)
        self.window.resize(1100, 700)
        self.actions = []
        self.window._set_error = lambda error: self.fail(str(error))
        class Service:
            def pending(service):
                return Result.success(True)
            def dismiss(service):
                self.actions.append("dismiss")
                return Result.success(None)
        self.controller = GettingStartedController(self.window, Service(), job_runner=ImmediateJobRunner())
        self.window.show()
        self.app.processEvents()

    def test_guidance_waits_for_the_editor_and_can_be_dismissed_and_reopened(self):
        window, controller = self.window, self.controller
        self.assertIsNone(controller.dialog)
        controller._load()
        self.assertIsNone(controller.dialog)
        window.entry_panel.is_busy = False
        window.entry_panel.is_dirty = True
        window.entry_panel.busy_changed.emit(False)
        self.assertIsNone(controller.dialog)
        window.entry_panel.is_dirty = False
        window.entry_panel.dirty_changed.emit(False)
        dialog = controller.dialog
        self.assertIs(self.app.activeModalWidget(), dialog)
        self.assertFalse(dialog.spotlight_rect.isEmpty())
        self.assertEqual(self.actions, [])
        self.app.processEvents()
        for _index in range(8):
            QTest.keyClick(dialog, Qt.Key.Key_Tab)
            self.assertTrue(dialog.isAncestorOf(self.app.focusWidget()))
        dialog.dismiss_button.click()
        self.assertIsNone(controller.dialog)
        controller.open()
        self.assertTrue(controller.dialog.isVisible())
        controller.dialog.record_button.click()
        self.app.processEvents()
        self.assertEqual(self.actions, ["dismiss", "dismiss"])
        self.assertEqual(window.entry_panel.start_input.text(), "09:00")
        self.assertTrue(window.entry_panel.start_input.hasFocus())
        self.assertIsNone(controller.dialog)
        controller._ready()
        self.assertIsNone(controller.dialog)
        window.close()

    def test_guidance_waits_for_other_dialogs_and_adapts_to_small_windows(self):
        window, controller = self.window, self.controller
        window.entry_panel.is_busy = False
        other = QDialog(window)
        other.setModal(True)
        other.show()
        controller._load()
        self.assertIsNone(controller.dialog)
        other.reject()
        controller._ready()
        dialog = controller.dialog
        window.resize(420, 520)
        self.app.processEvents()
        dialog.sync_geometry()
        self.assertTrue(dialog.spotlight_rect.isEmpty())
        self.assertTrue(dialog.rect().contains(dialog.card.geometry()))
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        self.assertIsNone(controller.dialog)
        self.assertEqual(self.actions, ["dismiss"])
        self.assertIsNone(self.app.activeModalWidget())
