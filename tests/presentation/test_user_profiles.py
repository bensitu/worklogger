"""Display-name editing, keyboard controls, failure recovery, and live identity labels."""

from dataclasses import replace
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QMessageBox

from worklogger.bootstrap import DesktopRuntimeConfig, build_desktop_runtime
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.language_preferences import LanguagePreferences
from worklogger.infrastructure.repositories import SQLiteAuthRepository
from worklogger.infrastructure.security import PBKDF2PasswordHasher
from worklogger.presentation.job_runner import ImmediateJobRunner
from tests.presentation.qt_support import dispose_test_windows


class UserProfilePresentationTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        preferences = Path(directory) / "preferences.ini"
        self.enterContext(patch("worklogger.bootstrap.LanguagePreferences", side_effect=lambda:
            LanguagePreferences(QSettings(str(preferences), QSettings.Format.IniFormat))))
        self.enterContext(patch.dict(os.environ, {"WORKLOGGER_LANG": "en_US"}))
        self.config = DesktopRuntimeConfig(database_path=Path(directory) / "worklog.db", create_user_if_empty=True,
            bootstrap_username="han_meimei", password_iterations=1000)
        result = build_desktop_runtime(self.config, argv=[])
        self.assertTrue(result.ok, result.error)
        self.runtime = result.value
        self.addCleanup(dispose_test_windows)
        self.addCleanup(self.runtime.local_inference.close)
        self.addCleanup(lambda: self.runtime.job_runner.shutdown(wait=True))
        self.auth = SQLiteAuthRepository(self.runtime.connection_factory, password_hasher=PBKDF2PasswordHasher(iterations=1000))
        self.controller = self.runtime.window._settings_workflow
        self.controller._job_runner = ImmediateJobRunner()
        self.page = self.runtime.window.settings_page
        self.editor = self.page.display_name_editor

    def save_name(self, name):
        self.editor.begin_editing()
        self.editor.input.setText(name)
        QTest.keyClick(self.editor.input, Qt.Key.Key_Return)

    def test_save_cancel_clear_and_restart_keep_login_id_independent(self):
        self.assertEqual(self.page.current_user_id_line_edit.text(), "han_meimei")
        self.assertTrue(self.page.current_user_id_line_edit.isReadOnly())
        self.save_name("Mary")
        self.assertEqual(self.runtime.window.sidebar.profile_name_label.text(), "Mary")
        self.assertEqual(self.auth.get_by_id(self.runtime.user.id).username, "han_meimei")
        self.assertTrue(self.editor.input.isReadOnly())
        self.editor.begin_editing()
        self.editor.input.setText("Unsubmitted name")
        self.page.current_user_id_line_edit.setFocus()
        self.assertEqual(self.auth.get_by_id(self.runtime.user.id).display_name, "Mary")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.assertFalse(self.runtime.window._confirm_discard_changes_if_needed())
        QTest.keyClick(self.editor.input, Qt.Key.Key_Escape)
        self.assertEqual(self.editor.input.text(), "Mary")
        self.assertTrue(self.editor.input.isReadOnly())
        self.save_name("")
        self.assertEqual(self.runtime.window.sidebar.profile_name_label.text(), "han_meimei")
        self.save_name("Mary")
        reopened = build_desktop_runtime(replace(self.config, minimal_mode=True), argv=[]).value
        self.addCleanup(reopened.local_inference.close)
        self.addCleanup(lambda: reopened.job_runner.shutdown(wait=True))
        reopened.window.refresh()
        self.assertIn("Mary", reopened.window.account_label.text())
        self.assertEqual(reopened.user.effective_display_name, "Mary")
        self.assertEqual(reopened.user.username, "han_meimei")

    def test_conflicts_and_failed_saves_preserve_input_and_restore_controls(self):
        self.save_name("Mary")
        self.editor.begin_editing()
        self.editor.input.setText("Beth")
        self.auth.set_display_name(self.runtime.user.id, "Amy", expected_display_name="Mary")
        self.editor.save_button.click()
        self.assertEqual(self.page.last_error.code, "user_profile_conflict")
        self.assertEqual(self.editor.input.text(), "Beth")
        self.assertEqual(self.runtime.window.sidebar.profile_name_label.text(), "Amy")
        self.editor.cancel_button.click()
        self.assertEqual(self.editor.input.text(), "Amy")
        self.editor.begin_editing()
        self.editor.input.setText("Beth")
        error = InfrastructureError("user_profile_save_failed", "user_profile_save_failed")
        with patch.object(self.controller._profile_service, "save_display_name", return_value=Result.failure(error)):
            self.editor.save_button.click()
        self.assertFalse(self.page.is_busy)
        self.assertTrue(self.editor.save_button.isEnabled())
        self.assertEqual(self.editor.input.text(), "Beth")
        self.assertFalse(self.editor.error_label.isHidden())
        self.editor.save_button.click()
        self.assertIsNone(self.page.last_error)
        self.assertEqual(self.runtime.window.sidebar.profile_name_label.text(), "Beth")

    def test_modal_keyboard_save_and_cancel_do_not_close_the_settings_dialog(self):
        dialog = self.controller.create_dialog(self.runtime.window)
        self.addCleanup(dialog.deleteLater)
        dialog.profile_changed.connect(self.runtime.window.apply_user_profile)
        dialog.show()
        dialog.page.category_nav.set_category("account")
        editor = dialog.display_name_editor
        editor.begin_editing()
        editor.input.setText("Mary")
        QTest.keyClick(editor.input, Qt.Key.Key_Return)
        self.assertTrue(dialog.isVisible())
        self.assertEqual(editor.input.text(), "Mary")
        editor.begin_editing()
        editor.input.setText("Cancelled")
        QTest.keyClick(editor.input, Qt.Key.Key_Escape)
        self.assertTrue(dialog.isVisible())
        self.assertEqual(editor.input.text(), "Mary")
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
        dialog.close()

    def test_profile_mutation_runs_on_worker_and_blocks_duplicate_submissions(self):
        import threading
        self.controller._job_runner = self.runtime.job_runner
        self.editor.begin_editing()
        self.editor.input.setText("Mary")
        release = threading.Event()
        calls = []
        save = self.controller._profile_service.save_display_name
        def delayed(*args, **kwargs):
            calls.append(threading.get_ident())
            release.wait(3)
            return save(*args, **kwargs)
        with patch.object(self.controller._profile_service, "save_display_name", side_effect=delayed):
            self.editor.save_button.click()
            self.assertTrue(self.page.is_busy)
            self.assertFalse(self.editor.save_button.isEnabled())
            with patch.object(QMessageBox, "information"):
                self.assertFalse(self.runtime.window._confirm_discard_changes_if_needed())
            try:
                self.runtime.application.processEvents()
            finally:
                release.set()
            deadline = time.monotonic() + 3
            while self.page.is_busy and time.monotonic() < deadline:
                self.runtime.application.processEvents()
                time.sleep(0.005)
        self.assertFalse(self.page.is_busy)
        self.assertEqual(len(calls), 1)
        self.assertNotEqual(calls[0], threading.get_ident())
        self.assertEqual(self.runtime.window.sidebar.profile_name_label.text(), "Mary")
