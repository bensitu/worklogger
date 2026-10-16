"""Desktop exit codes and feedback for authentication cancellation."""

from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

from worklogger.domain.shared.errors import CancellationError, InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import _, set_language
from worklogger.main import DesktopAlreadyRunningError, _acquire_instance_lock, run_desktop


class DesktopExitTests(unittest.TestCase):
    def test_startup_verification_releases_workers_before_inference_resources(self):
        from worklogger.main import smoke_runtime_check

        for refreshed in (True, False):
            with self.subTest(refreshed=refreshed):
                resources = Mock()
                resources.window.refresh.return_value = refreshed
                resources.window.last_error = None
                runtime = SimpleNamespace(window=resources.window, job_runner=resources.runner,
                                          local_inference=resources.inference)
                with patch("worklogger.bootstrap.build_desktop_runtime", return_value=Result.success(runtime)), redirect_stdout(io.StringIO()):
                    self.assertEqual(smoke_runtime_check(), 0 if refreshed else 1)
                resources.assert_has_calls([
                    call.window.close(),
                    call.runner.shutdown(wait=True),
                    call.inference.close(),
                ])

    def test_logout_disposes_resident_window_before_authenticating_again(self):
        from shiboken6 import isValid
        from tests.presentation.test_app_window import _app, _entry_model, MemoryWorkLogRepository
        from worklogger.presentation.shell import MinimalView
        from worklogger.presentation.job_runner import ImmediateJobRunner

        _app()
        residency = Mock()
        residency.quit_requested = False
        residency.should_keep_resident.return_value = True
        model = _entry_model(MemoryWorkLogRepository())
        window = MinimalView(time_entry_view_model=model, residency_controller=residency, job_runner=ImmediateJobRunner())
        window.refresh()
        self.assertTrue(model.start("break", "Ongoing record").ok)
        window.entry_panel.time_tabs.setCurrentIndex(1)
        timer = window.entry_panel.auto_timer
        self.assertTrue(timer.isActive())
        runtime = SimpleNamespace(application=Mock(), window=window, remember_session_store=Mock(),
                                  revoke_remembered_session=Mock(return_value=Result.success(None)))
        runtime.remember_session_store.clear_token.return_value = Result.success(None)
        runtime.application.exec.side_effect = lambda: window.logout_requested.emit() or 0
        calls = []

        def build(config, **_kwargs):
            calls.append(config)
            if len(calls) == 1:
                return Result.success(runtime)
            self.assertFalse(isValid(window))
            self.assertFalse(isValid(timer))
            return Result.failure(CancellationError("auth_cancelled", "auth_cancelled"))

        with (patch("worklogger.main._acquire_instance_lock"),
              patch("worklogger.bootstrap.build_authenticated_desktop_runtime", side_effect=build)):
            self.assertEqual(run_desktop([]), 0)
        self.assertEqual(len(calls), 2)

    def test_session_file_failure_after_revocation_returns_to_manual_authentication(self):
        runtime = SimpleNamespace(application=Mock(), window=Mock(), remember_session_store=Mock(),
                                  revoke_remembered_session=Mock(return_value=Result.success(None)))
        callbacks = []
        runtime.window.logout_requested.connect.side_effect = callbacks.append
        runtime.application.exec.side_effect = lambda: callbacks[0]() or 0
        runtime.remember_session_store.clear_token.return_value = Result.failure(
            InfrastructureError("remember_session_clear_failed", "remember_session_clear_failed"))
        captured = []

        def build(config, **_kwargs):
            captured.append(config)
            return Result.success(runtime) if len(captured) == 1 else Result.failure(CancellationError("auth_cancelled", "auth_cancelled"))

        with (patch("worklogger.main._acquire_instance_lock"), patch("worklogger.main._startup_message") as feedback,
              patch("worklogger.bootstrap.build_authenticated_desktop_runtime", side_effect=build)):
            self.assertEqual(run_desktop([]), 0)
        runtime.revoke_remembered_session.assert_called_once()
        self.assertTrue(captured[1].skip_remembered_session)
        feedback.assert_called_once()
        runtime.window.close.assert_called_once()

    def test_failed_session_revocation_does_not_claim_logout_success(self):
        runtime = SimpleNamespace(application=Mock(), window=Mock(), remember_session_store=Mock(),
                                  revoke_remembered_session=Mock(return_value=Result.failure(
                                      InfrastructureError("auth_state_failed", "auth_state_failed"))))
        callbacks = []
        runtime.window.logout_requested.connect.side_effect = callbacks.append
        runtime.application.exec.side_effect = lambda: callbacks[0]() or 0
        self.run_with_results(Result.success(runtime))
        runtime.remember_session_store.clear_token.assert_not_called()
        runtime.window.close.assert_not_called()
        runtime.application.quit.assert_not_called()

    def test_pending_restore_choice_recovers_before_retrying_authentication(self):
        from worklogger.domain.shared.recovery import RestoreRecoveryChoices

        pending = Result.failure(InfrastructureError("restore_pending", "restore_pending"))
        cancelled = Result.failure(CancellationError("auth_cancelled", "auth_cancelled"))
        with (patch.dict("os.environ", {"QT_QPA_PLATFORM": "interactive-test"}),
              patch("worklogger.bootstrap._application"),
              patch("worklogger.infrastructure.language_preferences.initialize_language"),
              patch("worklogger.infrastructure.database.restore_recovery.inspect_pending_restore",
                    return_value=RestoreRecoveryChoices(True, True)),
              patch("worklogger.presentation.widgets.restore_recovery.choose_restore_recovery", return_value="rollback"),
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
              patch("worklogger.presentation.widgets.restore_recovery.choose_restore_recovery", return_value=None),
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
