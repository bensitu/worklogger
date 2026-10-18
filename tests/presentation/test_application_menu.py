"""Focused editing, contextual saving, and protected desktop menu operations."""

from datetime import date
import os
from types import SimpleNamespace
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QLineEdit, QPlainTextEdit, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from tests.presentation.qt_support import dispose_test_windows
from tests.presentation.test_app_window import _app, _entry_model, _window, MemoryWorkLogRepository
from worklogger.presentation.shell import MinimalView, MinimalViewConfig
from worklogger.presentation.shell.menu_bar import ApplicationMenuController


class ApplicationMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        self.addCleanup(dispose_test_windows)
        self.addCleanup(self.app.clipboard().setText, self.app.clipboard().text())
        self.window = QWidget()
        self.window.entry_panel = SimpleNamespace(is_busy=False)
        self.layout = QVBoxLayout(self.window)
        self.window.save_button = QPushButton("Save", self.window)
        self.layout.addWidget(self.window.save_button)
        self.saved = []
        self.window.save_button.clicked.connect(lambda: self.saved.append("main"))
        self.menu = ApplicationMenuController(
            self.window, new_record=lambda: None, save_target=lambda: self.window.save_button,
            settings=None, routes={"calendar": None, "analytics": None, "reports": None, "settings": None},
            quit_app=lambda: None,
        )
        self.window.show()
        self.window.activateWindow()
        self.app.processEvents()

    def focus(self, editor):
        self.layout.addWidget(editor)
        editor.show()
        self.window.activateWindow()
        editor.setFocus()
        self.app.processEvents()
        self.assertIs(QApplication.focusWidget(), editor)
        self.menu.refresh()

    def text(self, editor):
        return editor.text() if isinstance(editor, QLineEdit) else editor.toPlainText()

    def test_edit_commands_follow_the_focused_text_editor(self):
        for editor_type in (QLineEdit, QTextEdit, QPlainTextEdit):
            with self.subTest(editor=editor_type.__name__):
                editor = editor_type(self.window)
                self.focus(editor)
                if isinstance(editor, QLineEdit):
                    editor.insert("Editable text")
                else:
                    editor.insertPlainText("Editable text")
                self.menu.actions["select_all"].trigger()
                self.menu.actions["copy"].trigger()
                self.assertEqual(self.app.clipboard().text(), "Editable text")
                self.menu.actions["cut"].trigger()
                self.assertEqual(self.text(editor), "")
                self.app.clipboard().setText("Replacement text")
                self.menu.actions["paste"].trigger()
                self.assertEqual(self.text(editor), "Replacement text")
                self.menu.actions["undo"].trigger()
                self.assertEqual(self.text(editor), "")
                self.menu.actions["redo"].trigger()
                self.assertEqual(self.text(editor), "Replacement text")
                editor.hide()
                editor.deleteLater()
                self.app.processEvents()

    def test_readonly_and_hidden_fields_retain_their_editing_restrictions(self):
        self.app.clipboard().setText("Existing clipboard text")
        editor = QLineEdit(self.window)
        editor.setEchoMode(QLineEdit.EchoMode.Password)
        editor.setText("Synthetic credential")
        self.focus(editor)
        editor.selectAll()
        self.menu.refresh()
        self.assertFalse(self.menu.actions["copy"].isEnabled())
        self.assertFalse(self.menu.actions["cut"].isEnabled())
        self.menu.actions["copy"].trigger()
        self.assertEqual(self.app.clipboard().text(), "Existing clipboard text")
        editor.setEchoMode(QLineEdit.EchoMode.Normal)
        editor.setReadOnly(True)
        editor.selectAll()
        self.menu.refresh()
        self.assertTrue(self.menu.actions["copy"].isEnabled())
        for operation in ("cut", "paste", "undo", "redo"):
            self.assertFalse(self.menu.actions[operation].isEnabled())
        editor.setEnabled(False)
        self.menu.refresh()
        for operation in ("cut", "copy", "paste", "undo", "redo", "select_all"):
            self.assertFalse(self.menu.actions[operation].isEnabled())

    def test_save_tracks_the_existing_button_and_busy_state(self):
        self.menu.refresh()
        self.window.save_button.setEnabled(False)
        self.assertFalse(self.menu.actions["save"].isEnabled())
        self.menu.actions["save"].trigger()
        self.assertEqual(self.saved, [])
        self.window.save_button.setEnabled(True)
        self.assertTrue(self.menu.actions["save"].isEnabled())
        self.menu.actions["save"].trigger()
        self.assertEqual(self.saved, ["main"])
        self.window.entry_panel.is_busy = True
        self.menu.refresh()
        self.assertFalse(self.menu.actions["new"].isEnabled())

    def test_modal_save_and_close_apply_to_the_active_dialog(self):
        class ProtectedDialog(QDialog):
            allow_close = False

            def closeEvent(self, event):
                if self.allow_close:
                    super().closeEvent(event)
                else:
                    event.ignore()

        dialog = ProtectedDialog(self.window)
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        layout = QVBoxLayout(dialog)
        editor = QLineEdit(dialog)
        layout.addWidget(editor)
        dialog.save_button = QPushButton("Save", dialog)
        layout.addWidget(dialog.save_button)
        dialog.save_button.clicked.connect(lambda: self.saved.append("dialog"))
        dialog.show()
        dialog.activateWindow()
        editor.setFocus()
        self.app.processEvents()
        self.menu.refresh()
        self.assertFalse(self.menu.actions["new"].isEnabled())
        self.assertFalse(self.menu.actions["quit"].isEnabled())
        self.menu.actions["save"].trigger()
        self.assertEqual(self.saved, ["dialog"])
        self.menu.actions["close"].trigger()
        self.assertTrue(dialog.isVisible())
        dialog.allow_close = True
        self.menu.actions["close"].trigger()
        self.assertFalse(dialog.isVisible())
        self.assertTrue(self.window.isVisible())

    def test_record_save_new_and_quit_preserve_the_window_workflows(self):
        self.window.hide()
        self.menu.dispose()
        for minimal in (False, True):
            with self.subTest(minimal=minimal):
                records = MemoryWorkLogRepository()
                day = date(2026, 4, 20)
                window = (MinimalView(time_entry_view_model=_entry_model(records), config=MinimalViewConfig(
                    today=day, selected_day=day, confirm_discard_changes=lambda: False,
                )) if minimal else _window(records, confirm_discard_changes=lambda: False))
                menu = window.application_menu or ApplicationMenuController(
                    window, new_record=window.new_record, save_target=lambda: window.entry_panel.save_button,
                    settings=None, routes={"calendar": None, "analytics": None, "reports": None, "settings": None},
                    quit_app=window.lifecycle_controller.request_quit,
                )
                window.refresh()
                window.show()
                window.activateWindow()
                panel = window.entry_panel
                panel.start_input.setText("09:00")
                panel.end_input.setText("10:00")
                panel.content_input.setPlainText("Saved work content")
                panel.content_input.setFocus()
                self.app.processEvents()
                menu.refresh()
                menu.actions["save"].trigger()
                self.assertEqual(records.get_for_day(1, day).note, "Saved work content")
                panel.content_input.insertPlainText(" changed")
                menu.refresh()
                draft = panel.content_input.toPlainText()
                menu.actions["new"].trigger()
                self.assertEqual(panel.content_input.toPlainText(), draft)
                menu.actions["quit"].trigger()
                self.assertTrue(window.isVisible())
                self.assertEqual(records.get_for_day(1, day).note, "Saved work content")
                panel.discard_changes()
                window.close()
                menu.dispose()
                window.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
