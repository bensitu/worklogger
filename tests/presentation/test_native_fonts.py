"""Native Windows font rendering checks using an isolated desktop runtime."""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


def check_native_login_fonts() -> None:
    from PySide6.QtCore import QEventLoop, QSettings, QTimer, Qt, qInstallMessageHandler
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLineEdit, QMenu, QPlainTextEdit, QSystemTrayIcon, QTextEdit

    from tests.infrastructure.test_auth_schema_migration import legacy_database
    from tests.presentation.test_report_history_widgets import WindowShowObserver
    from worklogger.bootstrap import DesktopRuntimeConfig, build_authenticated_desktop_runtime
    from worklogger.domain.shared.result import Result
    from worklogger.domain.reporting.models import Report
    from worklogger.domain.reporting.periods import daily_period, weekly_period, monthly_period
    from worklogger.infrastructure.i18n import available_languages, set_language
    from worklogger.infrastructure.language_preferences import LanguagePreferences
    from worklogger.infrastructure.repositories import SQLiteReportRepository
    from worklogger.presentation.auth import AuthController, LoginDialog
    from worklogger.presentation.widgets import ExportMenuButton

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    assert app.platformName() == "windows"
    messages: list[str] = []
    previous = qInstallMessageHandler(lambda _kind, _context, message: messages.append(message))
    runtime = None
    dialogs: list[LoginDialog] = []
    directory = tempfile.TemporaryDirectory()

    def process_events() -> None:
        loop = QEventLoop()
        QTimer.singleShot(100, loop.quit)
        loop.exec()

    def check_menu(menu, parent):
        menu.popup(parent.mapToGlobal(parent.rect().center()))
        process_events()
        assert menu.isVisible()
        for action in menu.actions():
            if action.menu() is not None:
                check_menu(action.menu(), parent)
        menu.close()

    def check_context_menus(parent):
        for editor in parent.findChildren(QLineEdit) + parent.findChildren(QTextEdit) + parent.findChildren(QPlainTextEdit):
            if editor.isVisible():
                menu = editor.createStandardContextMenu()
                try:
                    check_menu(menu, editor)
                finally:
                    menu.deleteLater()

    try:
        try:
            root = Path(directory.name)
            path = root / "worklog.db"
            legacy_database(path)
            session_store = Mock()
            session_store.load_token.return_value = Result.success(None)
            session_store.clear_token.return_value = Result.success(None)
            preferences = lambda: LanguagePreferences(
                QSettings(str(root / "preferences.ini"), QSettings.Format.IniFormat)
            )

            def login_dialog(parent):
                dialog = LoginDialog(parent)
                dialogs.append(dialog)
                dialog.username_input.setText("admin")
                dialog.password_input.setText("test-password")
                QTimer.singleShot(100, dialog.login_button.click)
                QTimer.singleShot(3_000, dialog, dialog.reject)
                return dialog

            with patch("worklogger.bootstrap.LanguagePreferences", side_effect=preferences), \
                 patch("worklogger.bootstrap._remember_session_store", return_value=session_store), \
                 patch("worklogger.infrastructure.language_preferences.detect_system_language", return_value="en_US"):
                result = build_authenticated_desktop_runtime(
                    DesktopRuntimeConfig(database_path=path, password_iterations=1_000),
                    argv=[],
                    auth_controller_factory=lambda model: AuthController(
                        model, login_dialog_factory=login_dialog, remember_session_store=session_store,
                    ),
                )
                assert result.ok, result.error
                runtime = result.value
                window = runtime.window
                assert window.refresh()
                window.show()
                process_events()
                assert not [message for message in messages if "QFont::" in message], messages

                for language in available_languages():
                    set_language(language)
                    dialog = LoginDialog()
                    dialogs.append(dialog)
                    dialog.show()
                    process_events()
                    check_context_menus(dialog)
                    dialog.close()
                set_language("en_US")
                report_repository = SQLiteReportRepository(runtime.connection_factory)
                day = window.selected_day
                for period in (daily_period(day), weekly_period(day), monthly_period(day.year, day.month)):
                    report_repository.save(Report(None, runtime.user.id, period.report_type,
                                                  period.start, period.end, "Saved report"))
                for dark in (False, True):
                    window._config = replace(window._config, dark=dark)
                    window.apply_theme()
                    for route in ("calendar", "reports", "analytics", "settings"):
                        observer = WindowShowObserver(window)
                        if route == "reports":
                            app.installEventFilter(observer)
                        try:
                            window.sidebar._buttons[route].click()
                            process_events()
                            if route == "reports":
                                for report_type in ("daily", "weekly", "monthly"):
                                    window.reports_page.report_type_control.set_value(report_type)
                                    process_events()
                                assert not observer.unexpected_windows, observer.unexpected_windows
                        finally:
                            if route == "reports":
                                app.removeEventFilter(observer)
                        check_context_menus(window)
                        if route == "settings":
                            for category in window.settings_page._category_pages:
                                window.settings_page.category_nav.set_category(category)
                                process_events()
                                check_context_menus(window)
                        buttons = window.findChildren(ExportMenuButton)
                        if route == "calendar":
                            buttons.append(window.calendar_page.add_entry_button)
                        for button in buttons:
                            if not button.isVisible() or not button.isEnabled():
                                continue
                            menu = button.menu()
                            assert menu is not None
                            opened = []

                            def close_menu():
                                opened.append(True)
                                QTimer.singleShot(50, menu.close)

                            menu.aboutToShow.connect(close_menu)
                            try:
                                QTest.mouseClick(button, Qt.MouseButton.LeftButton)
                                process_events()
                                assert opened, button.objectName()
                            finally:
                                menu.aboutToShow.disconnect(close_menu)
                    for tray in window.findChildren(QSystemTrayIcon):
                        check_menu(tray.contextMenu(), window)
                    nested = QMenu(window)
                    nested.addMenu("Options").addAction("Choice")
                    check_menu(nested, window)
                    nested.deleteLater()
                assert not [message for message in messages if "QFont::" in message], messages
                print("Native login, main window, routes, menu buttons, five languages and both themes: no QFont warnings.")
        finally:
            if runtime is not None:
                runtime.window.close()
    finally:
        for dialog in dialogs:
            dialog.deleteLater()
        qInstallMessageHandler(previous)
        directory.cleanup()


@unittest.skipUnless(sys.platform == "win32", "Requires the native Windows Qt platform")
class NativeFontTests(unittest.TestCase):
    def test_login_and_main_window_render_without_font_warnings(self) -> None:
        environment = dict(os.environ, QT_QPA_PLATFORM="windows", QT_STYLE_OVERRIDE="windows11", WORKLOGGER_LANG="")
        result = subprocess.run(
            [sys.executable, "-m", "tests.presentation.test_native_fonts", "--native-font-check"],
            cwd=Path(__file__).resolve().parents[2], env=environment,
            capture_output=True, text=True, timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    if "--native-font-check" in sys.argv:
        check_native_login_fonts()
    else:
        unittest.main()
