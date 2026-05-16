from __future__ import annotations

from datetime import date
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from worklogger.bootstrap import (
    DesktopRuntimeConfig,
    build_authenticated_desktop_runtime,
    build_desktop_runtime,
)
from worklogger.config.constants import (
    GITHUB_LATEST_RELEASE_API_URL,
    MINIMAL_MODE_SETTING_KEY,
)
from worklogger.domain.shared.errors import CancellationError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkType
from worklogger.infrastructure.repositories import SQLiteSettingsRepository, SQLiteWorkLogRepository
from worklogger.main import main
from worklogger.presentation.auth import AuthSession
from worklogger.presentation.shell import AppWindowConfig, MinimalView
from worklogger.presentation.viewmodels import AuthViewModel


class AutoRegisterAuthenticator:
    def __init__(self, view_model: AuthViewModel) -> None:
        self._view_model = view_model

    def authenticate(self) -> Result[AuthSession]:
        registered = self._view_model.register(
            username="alice",
            password="secret123",
            password_confirm="secret123",
        )
        if not registered.ok or registered.value is None:
            return Result.failure(registered.error)
        return Result.success(
            AuthSession(
                user=registered.value.user,
                recovery_key=registered.value.recovery_key,
            )
        )


class CancellingAuthenticator:
    def __init__(self, view_model: AuthViewModel) -> None:
        self._view_model = view_model

    def authenticate(self) -> Result[AuthSession]:
        return Result.failure(CancellationError("auth_cancelled", "auth_cancelled"))


class RuntimeBootstrapTests(unittest.TestCase):
    def test_runtime_bootstrap_builds_sqlite_backed_app_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "worklog.db"

            runtime = build_desktop_runtime(
                DesktopRuntimeConfig(
                    database_path=database_path,
                    create_user_if_empty=True,
                    password_iterations=1_000,
                    window=AppWindowConfig(
                        selected_day=date(2026, 4, 20),
                        today=date(2026, 4, 13),
                        monthly_target_hours=40.0,
                    ),
                ),
                argv=[],
            )

            self.assertTrue(runtime.ok, runtime.error)
            assert runtime.value is not None
            self.assertEqual(runtime.value.user.username, "local")
            self.assertEqual(runtime.value.window.account_label.text(), "Signed in: local")
            self.assertIsNotNone(runtime.value.job_runner)
            settings_workflow = getattr(runtime.value.window, "_settings_workflow")
            ai_workflow = getattr(runtime.value.window, "_ai_assist_workflow")
            local_models_workflow = getattr(settings_workflow, "_local_models_workflow")
            self.assertIs(settings_workflow._job_runner, runtime.value.job_runner)
            self.assertIs(ai_workflow._job_runner, runtime.value.job_runner)
            self.assertIs(local_models_workflow._job_runner, runtime.value.job_runner)
            self.assertTrue(database_path.exists())
            self.assertTrue(runtime.value.window.refresh())

            runtime.value.window.entry_panel.start_input.setText("09:00")
            runtime.value.window.entry_panel.end_input.setText("18:00")
            runtime.value.window.entry_panel.note_input.setPlainText("SQLite backed")
            runtime.value.window.entry_panel.save_button.click()

            saved = SQLiteWorkLogRepository(
                runtime.value.connection_factory
            ).get_for_day(runtime.value.user.id, date(2026, 4, 20))
            self.assertIsNotNone(saved)
            assert saved is not None
            self.assertEqual(saved.work_type, WorkType.NORMAL)
            self.assertEqual(saved.note, "SQLite backed")
            runtime.value.window.close()

    def test_runtime_bootstrap_switches_to_minimal_view_from_user_setting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "worklog.db"
            first = build_desktop_runtime(
                DesktopRuntimeConfig(
                    database_path=database_path,
                    create_user_if_empty=True,
                    password_iterations=1_000,
                    window=AppWindowConfig(
                        selected_day=date(2026, 4, 20),
                        today=date(2026, 4, 13),
                    ),
                ),
                argv=[],
            )
            self.assertTrue(first.ok, first.error)
            assert first.value is not None
            SQLiteSettingsRepository(first.value.connection_factory).set(
                first.value.user.id,
                MINIMAL_MODE_SETTING_KEY,
                "1",
            )
            first.value.window.close()

            runtime = build_desktop_runtime(
                DesktopRuntimeConfig(
                    database_path=database_path,
                    password_iterations=1_000,
                    window=AppWindowConfig(
                        selected_day=date(2026, 4, 20),
                        today=date(2026, 4, 13),
                    ),
                ),
                argv=[],
            )

            self.assertTrue(runtime.ok, runtime.error)
            assert runtime.value is not None
            self.assertIsInstance(runtime.value.window, MinimalView)
            self.assertTrue(runtime.value.window.refresh())
            self.assertEqual(runtime.value.window.date_label.text(), "2026-04-20")
            self.assertEqual(runtime.value.window.account_label.text(), "Signed in: local")
            runtime.value.window.close()

    def test_runtime_bootstrap_rejects_empty_database_without_bootstrap_user(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = build_desktop_runtime(
                DesktopRuntimeConfig(
                    database_path=Path(directory) / "worklog.db",
                    create_user_if_empty=False,
                    password_iterations=1_000,
                ),
                argv=[],
            )

            self.assertFalse(runtime.ok)
            self.assertEqual(runtime.error.code if runtime.error else "", "runtime_user_required")

    def test_authenticated_runtime_registers_first_user_before_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = build_authenticated_desktop_runtime(
                DesktopRuntimeConfig(
                    database_path=Path(directory) / "worklog.db",
                    password_iterations=1_000,
                    window=AppWindowConfig(
                        selected_day=date(2026, 4, 20),
                        today=date(2026, 4, 13),
                    ),
                ),
                argv=[],
                auth_controller_factory=AutoRegisterAuthenticator,
            )

            self.assertTrue(runtime.ok, runtime.error)
            assert runtime.value is not None
            self.assertEqual(runtime.value.user.username, "alice")
            self.assertEqual(runtime.value.window.account_label.text(), "Signed in: alice")
            self.assertIsNotNone(runtime.value.auth_session)
            assert runtime.value.auth_session is not None
            self.assertTrue(runtime.value.auth_session.recovery_key)
            self.assertTrue(runtime.value.window.refresh())
            runtime.value.window.close()

    def test_runtime_builders_share_remember_session_store_instance(self) -> None:
        with tempfile.TemporaryDirectory() as first_directory:
            first = build_desktop_runtime(
                DesktopRuntimeConfig(
                    database_path=Path(first_directory) / "worklog.db",
                    create_user_if_empty=True,
                    password_iterations=1_000,
                ),
                argv=[],
            )
            self.assertTrue(first.ok, first.error)
            assert first.value is not None

            with tempfile.TemporaryDirectory() as second_directory:
                second = build_authenticated_desktop_runtime(
                    DesktopRuntimeConfig(
                        database_path=Path(second_directory) / "worklog.db",
                        password_iterations=1_000,
                    ),
                    argv=[],
                    auth_controller_factory=AutoRegisterAuthenticator,
                )
                self.assertTrue(second.ok, second.error)
                assert second.value is not None

                self.assertIs(
                    first.value.remember_session_store,
                    second.value.remember_session_store,
                )
                self.assertIs(
                    getattr(second.value.window, "_settings_workflow")._remember_session_store,
                    second.value.remember_session_store,
                )
                second.value.window.close()
            first.value.window.close()

    def test_update_checker_url_comes_from_constants(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = build_authenticated_desktop_runtime(
                DesktopRuntimeConfig(
                    database_path=Path(directory) / "worklog.db",
                    password_iterations=1_000,
                ),
                argv=[],
                auth_controller_factory=AutoRegisterAuthenticator,
            )

            self.assertTrue(runtime.ok, runtime.error)
            assert runtime.value is not None
            settings_workflow = getattr(runtime.value.window, "_settings_workflow")
            checker = settings_workflow._update_check_handler._checker
            self.assertEqual(checker._api_url, GITHUB_LATEST_RELEASE_API_URL)
            runtime.value.window.close()

    def test_authenticated_runtime_stops_when_auth_is_cancelled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = build_authenticated_desktop_runtime(
                DesktopRuntimeConfig(
                    database_path=Path(directory) / "worklog.db",
                    password_iterations=1_000,
                ),
                argv=[],
                auth_controller_factory=CancellingAuthenticator,
            )

            self.assertFalse(runtime.ok)
            self.assertEqual(runtime.error.code if runtime.error else "", "auth_cancelled")

    def test_main_runtime_smoke_is_non_blocking(self) -> None:
        self.assertEqual(main(["--smoke-runtime"]), 0)

    def test_main_without_arguments_starts_desktop_runner(self) -> None:
        calls: list[list[str]] = []

        exit_code = main(
            [],
            desktop_runner=lambda args: calls.append(list(args)) or 17,
        )

        self.assertEqual(exit_code, 17)
        self.assertEqual(calls, [[]])

    def test_main_desktop_flag_starts_desktop_runner_without_launcher_flag(self) -> None:
        calls: list[list[str]] = []

        exit_code = main(
            ["--desktop", "--style", "Fusion"],
            desktop_runner=lambda args: calls.append(list(args)) or 19,
        )

        self.assertEqual(exit_code, 19)
        self.assertEqual(calls, [["--style", "Fusion"]])

    def test_script_path_entry_point_smoke_imports(self) -> None:
        workspace_root = Path(__file__).resolve().parents[2]
        completed = subprocess.run(
            [sys.executable, "worklogger/main.py", "--smoke-import"],
            cwd=workspace_root,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("SMOKE IMPORT OK", completed.stdout)


if __name__ == "__main__":
    unittest.main()
