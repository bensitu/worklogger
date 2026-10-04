"""Desktop exit codes and feedback for authentication cancellation."""

from contextlib import redirect_stdout
import io
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from worklogger.domain.shared.errors import CancellationError, InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import _, set_language
from worklogger.main import run_desktop


class DesktopExitTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_language("en_US")

    def run_with_results(self, *results):
        output = io.StringIO()
        with patch("worklogger.bootstrap.build_authenticated_desktop_runtime", side_effect=results) as builder, redirect_stdout(output):
            code = run_desktop([])
        return code, output.getvalue(), builder.call_count

    def test_initial_authentication_cancellation_exits_silently(self):
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
        for language in ("en_US", "zh_CN"):
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


if __name__ == "__main__":
    unittest.main()
