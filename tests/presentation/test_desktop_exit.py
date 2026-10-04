"""Desktop exit codes and feedback for authentication cancellation."""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication

from tests.infrastructure.test_auth_schema_migration import legacy_database
from worklogger.bootstrap import DesktopRuntimeConfig, build_authenticated_desktop_runtime
from worklogger.domain.shared.errors import CancellationError, InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import _, available_languages, set_language
from worklogger.infrastructure.language_preferences import LanguagePreferences
from worklogger.main import run_desktop
from worklogger.presentation.auth import AuthController, LoginDialog


class DesktopExitTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_language("en_US")

    def run_with_results(self, *results):
        output = io.StringIO()
        with patch("worklogger.bootstrap.build_authenticated_desktop_runtime", side_effect=results) as builder, redirect_stdout(output):
            code = run_desktop([])
        return code, output.getvalue(), builder.call_count

    def test_initial_authentication_cancellation_exits_silently_in_all_languages(self):
        for language in available_languages():
            with self.subTest(language=language):
                set_language(language)
                self.assertEqual(self.run_with_results(Result.failure(
                    CancellationError("auth_cancelled", "auth_cancelled"))), (0, "", 1))

    def test_cancellation_after_logout_exits_silently(self):
        runtime = SimpleNamespace(application=Mock(), window=Mock(), remember_session_store=Mock())
        callbacks = []
        runtime.window.logout_requested.connect.side_effect = callbacks.append
        runtime.application.exec.side_effect = lambda: callbacks[0]() or 0
        self.assertEqual(self.run_with_results(Result.success(runtime), Result.failure(
            CancellationError("auth_cancelled", "auth_cancelled"))), (0, "", 2))
        runtime.remember_session_store.clear_token.assert_called_once_with()
        runtime.window.close.assert_called_once_with()

    def test_normal_main_window_exit_preserves_application_exit_code(self):
        runtime = SimpleNamespace(application=Mock(), window=Mock())
        runtime.application.exec.return_value = 17
        self.assertEqual(self.run_with_results(Result.success(runtime)), (17, "", 1))

    def test_real_startup_failures_remain_failures_and_are_translated(self):
        for language in available_languages():
            with self.subTest(language=language):
                set_language(language)
                code, output, calls = self.run_with_results(Result.failure(InfrastructureError(
                    "desktop_runtime_failed", "desktop_runtime_failed", {"reason": "private diagnostic"})))
                self.assertEqual((code, calls), (1, 1))
                self.assertIn(_("DESKTOP START FAILED"), output)
                self.assertIn(_("Unable to start WorkLogger. Check the application log for details."), output)
                self.assertNotIn("desktop_runtime_failed", output)
                self.assertNotIn("private diagnostic", output)

    def test_cancellation_code_without_cancellation_type_is_not_silenced(self):
        code, output, _calls = self.run_with_results(Result.failure(
            InfrastructureError("auth_cancelled", "auth_cancelled")))
        self.assertEqual(code, 1)
        self.assertIn("DESKTOP START FAILED", output)
        self.assertNotIn("auth_cancelled", output)

    def test_closing_real_login_dialog_is_a_normal_desktop_exit(self):
        application = QApplication.instance() or QApplication([])
        stylesheet, palette, font = application.styleSheet(), application.palette(), application.font()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "worklog.db"
            legacy_database(database)
            config = DesktopRuntimeConfig(database_path=database, password_iterations=1_000)
            store = Mock()
            store.load_token.return_value = Result.success(None)
            dialogs = []

            def login_dialog(parent):
                dialog = LoginDialog(parent)
                dialogs.append(dialog)
                QTimer.singleShot(100, dialog, dialog.close)
                QTimer.singleShot(2_000, dialog, dialog.reject)
                return dialog

            def build(config, *, argv):
                return build_authenticated_desktop_runtime(config, argv=argv,
                    auth_controller_factory=lambda model: AuthController(model,
                        login_dialog_factory=login_dialog, remember_session_store=store))

            output = io.StringIO()
            try:
                with patch("worklogger.bootstrap.DesktopRuntimeConfig", return_value=config), \
                     patch("worklogger.bootstrap.build_authenticated_desktop_runtime", side_effect=build), \
                     patch("worklogger.bootstrap._remember_session_store", return_value=store), \
                     patch("worklogger.bootstrap.LanguagePreferences", side_effect=lambda: LanguagePreferences(
                         QSettings(str(root / "preferences.ini"), QSettings.Format.IniFormat))), \
                     patch("worklogger.bootstrap.setup_logging"), \
                     patch("worklogger.bootstrap._build_runtime_for_user") as build_window, \
                     redirect_stdout(output):
                    self.assertEqual(run_desktop([]), 0)
                self.assertEqual(len(dialogs), 1)
                self.assertEqual(output.getvalue(), "")
                build_window.assert_not_called()
                store.save_token.assert_not_called()
                store.clear_token.assert_not_called()
            finally:
                for dialog in dialogs:
                    dialog.deleteLater()
                application.setStyleSheet(stylesheet)
                application.setPalette(palette)
                application.setFont(font)


if __name__ == "__main__":
    unittest.main()
