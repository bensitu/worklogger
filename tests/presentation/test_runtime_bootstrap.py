from __future__ import annotations

from datetime import date
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QMessageBox

from tests.infrastructure.test_auth_schema_migration import legacy_database
from worklogger.bootstrap import (
    DesktopRuntimeConfig,
    build_authenticated_desktop_runtime,
    build_desktop_runtime,
)
from worklogger.config.constants import (
    GITHUB_LATEST_RELEASE_API_URL,
    MINIMAL_MODE_SETTING_KEY,
    SHOW_HOLIDAYS_SETTING_KEY,
)
from worklogger.domain.shared.errors import CancellationError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkType
from worklogger.infrastructure.repositories import SQLiteSettingsRepository, SQLiteWorkLogRepository
from worklogger.infrastructure.i18n import _, get_language, set_language
from worklogger.infrastructure.language_preferences import LanguagePreferences
from worklogger.infrastructure.calendar import PythonHolidaysProvider
from worklogger.main import main
from worklogger.presentation.auth import AuthSession, LoginDialog
from worklogger.presentation.settings import SettingsDialog
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
    def setUp(self):
        from tests.presentation.qt_support import dispose_test_windows
        self.addCleanup(dispose_test_windows)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.preferences_path = Path(directory.name) / "preferences.ini"
        self.preferences = self.new_preferences()
        self.enterContext(patch("worklogger.bootstrap.LanguagePreferences", side_effect=self.new_preferences))
        self.enterContext(patch.dict(os.environ, {"WORKLOGGER_LANG": ""}))
        self.system_language = self.enterContext(patch(
            "worklogger.infrastructure.language_preferences.detect_system_language", return_value="en_US"))
        self.addCleanup(set_language, "en_US")

    def new_preferences(self):
        return LanguagePreferences(QSettings(str(self.preferences_path), QSettings.Format.IniFormat))

    def test_disabled_optional_features_are_not_composed(self):
        with patch.dict(os.environ, {
            "WORKLOGGER_FEATURE_AI": "0", "WORKLOGGER_FEATURE_LOCAL_MODELS": "0",
            "WORKLOGGER_FEATURE_UPDATE_CHECK": "0",
        }), tempfile.TemporaryDirectory() as directory:
            result = build_authenticated_desktop_runtime(
                DesktopRuntimeConfig(database_path=Path(directory) / "worklog.db", password_iterations=1_000),
                argv=[], auth_controller_factory=AutoRegisterAuthenticator,
            )
            self.assertTrue(result.ok, result.error)
            try:
                window = result.value.window
                self.assertFalse(window.entry_panel.view_model.rewrite_available)
                self.assertIsNone(window._settings_workflow._local_models_workflow)
                self.assertIsNone(window._settings_workflow._update_check_handler)
                self.assertFalse(window.settings_page.check_updates_button.isEnabled())
                self.assertFalse(window.settings_page.manage_local_models_button.isEnabled())
            finally:
                result.value.window.close()

    def test_first_login_is_translated_before_authentication(self):
        with tempfile.TemporaryDirectory() as directory:
            for language in ("en_US", "ja_JP", "ko_KR", "zh_CN", "zh_TW"):
                self.system_language.return_value = language

                def authenticator(model, language=language):
                    self.assertEqual(get_language(), language)
                    dialog = LoginDialog()
                    self.assertEqual(dialog.login_button.text(), _("Login", language=language))
                    self.assertEqual(dialog.username_input.placeholderText(), _("Enter your ID", language=language))
                    dialog.deleteLater()
                    return CancellingAuthenticator(model)

                result = build_authenticated_desktop_runtime(
                    DesktopRuntimeConfig(database_path=Path(directory) / "worklog.db", password_iterations=1_000),
                    argv=[], auth_controller_factory=authenticator,
                )
                self.assertFalse(result.ok)
                self.assertEqual(result.error.code, "auth_cancelled")
                self.assertIsNone(self.preferences.load())

    def test_first_account_inherits_language_and_manual_choice_reaches_next_login(self):
        self.system_language.return_value = "ja_JP"
        with tempfile.TemporaryDirectory() as directory:
            config = DesktopRuntimeConfig(database_path=Path(directory) / "worklog.db", password_iterations=1_000)
            first = build_authenticated_desktop_runtime(config, argv=[], auth_controller_factory=AutoRegisterAuthenticator)
            self.assertTrue(first.ok, first.error)
            try:
                self.assertEqual(get_language(), "ja_JP")
                page = first.value.window.settings_page
                self.assertEqual(page.language_combo.currentData(), "ja_JP")
                self.assertIsNone(self.preferences.load())
                page.language_combo.setCurrentIndex(page.language_combo.findData("en_US"))
                self.assertEqual(self.preferences.load(), "en_US")
                self.assertEqual(SQLiteSettingsRepository(first.value.connection_factory).get(first.value.user.id, "language"), "en_US")
                self.assertEqual(get_language(), "ja_JP")
            finally:
                first.value.window.close()

            def authenticator(model):
                self.assertEqual(get_language(), "en_US")
                return CancellingAuthenticator(model)

            second = build_authenticated_desktop_runtime(config, argv=[], auth_controller_factory=authenticator)
            self.assertFalse(second.ok)
            self.assertEqual(second.error.code, "auth_cancelled")

    def test_public_holidays_load_toggle_and_survive_restart_in_real_runtime(self):
        expected = {holiday.day: holiday.name for holiday in PythonHolidaysProvider().list_for_range(
            "JP", date(2026, 5, 1), date(2026, 5, 31))}
        self.assertIn(date(2026, 5, 4), expected)
        with tempfile.TemporaryDirectory() as directory, patch("worklogger.bootstrap.detect_country", return_value="JP"), patch.object(QMessageBox, "information"):
            config = DesktopRuntimeConfig(database_path=Path(directory) / "worklog.db",
                create_user_if_empty=True, password_iterations=1_000,
                window=AppWindowConfig(selected_day=date(2026, 5, 4), today=date(2026, 5, 15)))
            result = build_desktop_runtime(config, argv=[])
            self.assertTrue(result.ok, result.error)
            runtime = result.value
            window = runtime.window
            settings = SQLiteSettingsRepository(runtime.connection_factory)

            def displayed_holidays():
                return {cell.day: cell.holiday_name for cell in window.calendar_view.state.cells
                        if cell.in_month and cell.is_holiday}

            try:
                self.assertIsNone(window._holidays)
                self.assertTrue(window.refresh())
                self.assertEqual(displayed_holidays(), expected)
                self.assertEqual(window.entry_panel.content_input.toPlainText(), "")
                self.assertFalse(window.has_unsaved_changes)
                window.settings_page.holidays_switch.set_checked(False)
                self.assertEqual(displayed_holidays(), {})
                self.assertEqual(window.entry_panel.content_input.toPlainText(), "")
                self.assertEqual(settings.get(runtime.user.id, SHOW_HOLIDAYS_SETTING_KEY), "0")
                window.settings_page.holidays_switch.set_checked(True)
                self.assertEqual(displayed_holidays(), expected)
                self.assertEqual(settings.get(runtime.user.id, SHOW_HOLIDAYS_SETTING_KEY), "1")
                window.entry_panel.content_input.setPlainText("Unsubmitted note")
                self.assertTrue(window.has_unsaved_changes)
                window.settings_page.holidays_switch.set_checked(False)
                self.assertEqual(displayed_holidays(), {})
                self.assertEqual(window.entry_panel.content_input.toPlainText(), "Unsubmitted note")
                window.settings_page.holidays_switch.set_checked(True)
                self.assertEqual(displayed_holidays(), expected)
                self.assertEqual(window.entry_panel.content_input.toPlainText(), "Unsubmitted note")
                window.entry_panel.content_input.clear()
                self.assertFalse(window.has_unsaved_changes)
                self.assertEqual(SQLiteWorkLogRepository(runtime.connection_factory).list_all(runtime.user.id), ())
                self.assertTrue(window.previous_month())
                self.assertIn(date(2026, 4, 29), displayed_holidays())
                self.assertTrue(window.next_month())
                self.assertEqual(displayed_holidays(), expected)
            finally:
                window.close()
            restarted = build_desktop_runtime(config, argv=[])
            self.assertTrue(restarted.ok, restarted.error)
            window = restarted.value.window
            try:
                self.assertTrue(window.refresh())
                self.assertTrue(window.settings_page.holidays_switch.is_checked())
                self.assertEqual(displayed_holidays(), expected)
            finally:
                window.close()

    def test_minimal_mode_logout_remains_available_only_in_settings_account(self):
        with tempfile.TemporaryDirectory() as directory:
            config = DesktopRuntimeConfig(database_path=Path(directory) / "worklog.db",
                                          create_user_if_empty=True, password_iterations=1_000)
            first = build_desktop_runtime(config, argv=[])
            self.assertTrue(first.ok, first.error)
            SQLiteSettingsRepository(first.value.connection_factory).set(first.value.user.id, MINIMAL_MODE_SETTING_KEY, "1")
            first.value.window.close()
            second = build_desktop_runtime(config, argv=[])
            self.assertTrue(second.ok, second.error)
            window = second.value.window
            requests = []
            window.logout_requested.connect(lambda: requests.append(True))

            def settings_dialog(model, parent):
                dialog = SettingsDialog(model, parent)
                dialog.category_nav.set_category("account")
                QTimer.singleShot(0, dialog, dialog.logout_button.click)
                QTimer.singleShot(2_000, dialog, dialog.reject)
                return dialog

            window._settings_workflow._dialog_factory = settings_dialog
            try:
                self.assertIsInstance(window, MinimalView)
                self.assertFalse(hasattr(window, "logout_button"))
                self.assertTrue(window.open_settings())
                self.assertEqual(requests, [True])
            finally:
                window.close()

    def test_legacy_admin_can_authenticate_after_startup_migration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "worklog.db"
            _, _, admin_id = legacy_database(path)

            class LegacyAdminAuthenticator:
                def __init__(self, model):
                    self.model = model

                def authenticate(self):
                    result = self.model.login(username="admin", password="test-password")
                    if not result.ok:
                        return Result.failure(result.error)
                    return Result.success(AuthSession(user=result.value.user))

            runtime = None
            try:
                runtime = build_authenticated_desktop_runtime(
                    DesktopRuntimeConfig(database_path=path, password_iterations=1_000),
                    argv=[],
                    auth_controller_factory=LegacyAdminAuthenticator,
                )
                self.assertTrue(runtime.ok, runtime.error)
                self.assertEqual(runtime.value.user.id, admin_id)
                self.assertTrue(runtime.value.user.is_admin)
                self.assertTrue(runtime.value.window.refresh())
                self.assertEqual(len(list(path.parent.glob("worklog.db.bak_upgrade_*"))), 1)
            finally:
                if runtime is not None and runtime.value is not None:
                    runtime.value.window.close()

    def test_saved_settings_apply_on_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = DesktopRuntimeConfig(
                database_path=Path(directory) / "worklog.db",
                create_user_if_empty=True, password_iterations=1_000,
            )
            first = build_desktop_runtime(config, argv=[])
            self.assertTrue(first.ok, first.error)
            runtime = first.value
            settings = SQLiteSettingsRepository(runtime.connection_factory)
            for key, value in {
                "language": "ja_JP", "dark_mode": "1", "standard_work_hours": "7.5",
                "default_break_hours": "0.75", "monthly_target_hours": "150",
                "show_holidays": "0", "week_start_monday": "1",
            }.items():
                settings.set(runtime.user.id, key, value)
            runtime.window.close()
            second = None
            try:
                second = build_desktop_runtime(config, argv=[])
                self.assertTrue(second.ok, second.error)
                window = second.value.window
                self.assertEqual(get_language(), "ja_JP")
                self.assertEqual(self.preferences.load(), "ja_JP")
                self.assertTrue(window._config.dark)
                self.assertEqual(window._config.standard_work_hours, 7.5)
                self.assertEqual(window._config.monthly_target_hours, 150)
                self.assertFalse(window._config.calendar_options.show_holidays)
                self.assertTrue(window._config.calendar_options.week_start_monday)
                self.assertTrue(window.refresh())
                self.assertEqual(window.entry_panel.view_model.default_break_hours, 0.75)
                self.assertFalse(window.entry_panel.view_model.rewrite_available)
            finally:
                if second is not None and second.value is not None:
                    second.value.window.close()
                set_language("en_US")

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
            notes_workflow = runtime.value.window._notes_workflow
            local_models_workflow = getattr(settings_workflow, "_local_models_workflow")
            self.assertIs(settings_workflow._job_runner, runtime.value.job_runner)
            self.assertIs(notes_workflow._job_runner, runtime.value.job_runner)
            self.assertIs(local_models_workflow._job_runner, runtime.value.job_runner)
            self.assertTrue(database_path.exists())
            self.assertTrue(runtime.value.window.refresh())

            runtime.value.window.entry_panel.start_input.setText("09:00")
            runtime.value.window.entry_panel.end_input.setText("18:00")
            runtime.value.window.entry_panel.content_input.setPlainText("SQLite backed")
            with patch("worklogger.presentation.shell.app_window.QMessageBox.information") as notification:
                runtime.value.window.entry_panel.save_button.click()
                deadline = time.monotonic() + 5
                while runtime.value.window.entry_panel.is_busy and time.monotonic() < deadline:
                    runtime.value.application.processEvents()
                    time.sleep(0.01)
                self.assertFalse(runtime.value.window.entry_panel.is_busy)
            notification.assert_not_called()

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
