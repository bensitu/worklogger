"""Desktop exit codes and feedback for authentication cancellation."""

from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from worklogger.domain.shared.errors import CancellationError, InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import _, set_language
from worklogger.main import DesktopAlreadyRunningError, _acquire_instance_lock, run_desktop


class DesktopExitTests(unittest.TestCase):
    def test_pending_restore_choice_recovers_before_retrying_authentication(self):
        from worklogger.domain.shared.recovery import RestoreRecoveryChoices

        pending = Result.failure(InfrastructureError("restore_pending", "restore_pending"))
        cancelled = Result.failure(CancellationError("auth_cancelled", "auth_cancelled"))
        with (patch.dict("os.environ", {"QT_QPA_PLATFORM": "interactive-test"}),
              patch("worklogger.bootstrap._application"),
              patch("worklogger.infrastructure.language_preferences.initialize_language"),
              patch("worklogger.infrastructure.database.restore_recovery.inspect_pending_restore",
                    return_value=RestoreRecoveryChoices(True, True)),
              patch("worklogger.presentation.auth.restore_recovery.choose_restore_recovery", return_value="rollback"),
              patch("worklogger.infrastructure.database.restore_recovery.recover_pending_restore") as recover):
            self.assertEqual(self.run_with_results(pending, cancelled), (0, "", 2))
            self.assertEqual(recover.call_args.args[1], "rollback")

    def test_cancelled_restore_recovery_leaves_files_untouched(self):
        from worklogger.domain.shared.recovery import RestoreRecoveryChoices

        pending = Result.failure(InfrastructureError("restore_pending", "restore_pending"))
        with (patch.dict("os.environ", {"QT_QPA_PLATFORM": "interactive-test"}),
              patch("worklogger.bootstrap._application"),
              patch("worklogger.infrastructure.language_preferences.initialize_language"),
              patch("worklogger.infrastructure.database.restore_recovery.inspect_pending_restore",
                    return_value=RestoreRecoveryChoices(True, False)),
              patch("worklogger.presentation.auth.restore_recovery.choose_restore_recovery", return_value=None),
              patch("worklogger.infrastructure.database.restore_recovery.recover_pending_restore") as recover):
            self.assertEqual(self.run_with_results(pending), (0, "", 1))
            recover.assert_not_called()

    def tearDown(self) -> None:
        set_language("en_US")

    def run_with_results(self, *results):
        output = io.StringIO()
        with patch("worklogger.main._acquire_instance_lock"), patch("worklogger.main._startup_message", side_effect=lambda message: print(message)), patch("worklogger.bootstrap.build_authenticated_desktop_runtime", side_effect=results) as builder, redirect_stdout(output):
            code = run_desktop([])
        return code, output.getvalue(), builder.call_count

    def test_initial_authentication_cancellation_exits_silently(self):
        self.assertEqual(self.run_with_results(Result.failure(
            CancellationError("auth_cancelled", "auth_cancelled"))), (0, "", 1))

    def test_database_instance_lock_excludes_another_owner_and_can_be_reacquired(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "worklog.db"
            lock = _acquire_instance_lock(path)
            try:
                with self.assertRaises(DesktopAlreadyRunningError):
                    _acquire_instance_lock(path)
            finally:
                lock.unlock()
            replacement = _acquire_instance_lock(path)
            replacement.unlock()

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
