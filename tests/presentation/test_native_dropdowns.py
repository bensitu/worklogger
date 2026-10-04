"""Render each dropdown first in an independent native Windows process."""

from dataclasses import replace
from datetime import date
import os
from pathlib import Path
import subprocess
import sys
import unittest


DROPDOWNS = (
    ("calendar", "work_type_combo"),
    ("analytics", "analytics_period_combo"),
    ("settings", "language_combo"),
    ("settings", "theme_combo"),
    ("settings", "mode_combo"),
    ("analytics_dialog", "scope_combo"),
    ("analytics_dialog", "metric_combo"),
    ("analytics_dialog", "chart_combo"),
    ("identity_dialog", "provider_combo"),
    ("file_dialog", "lookInCombo"),
    ("file_dialog", "fileTypeCombo"),
)


def check_dropdown(kind: str, name: str) -> None:
    from PySide6.QtCore import QEvent, QEventLoop, QTimer, Qt, qInstallMessageHandler
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QComboBox, QFileDialog, QStyle, QStyleOptionComboBox

    from tests.presentation.test_identity_presentation import FakeIdentityHandlers
    from tests.presentation.test_ui_layout import sample_window
    from worklogger.infrastructure.i18n import available_languages, set_language
    from worklogger.presentation.analytics import AnalyticsDialog
    from worklogger.presentation.identity import IdentityDialog
    from worklogger.presentation.viewmodels import IdentityManagementViewModel

    application = QApplication([])
    application.setQuitOnLastWindowClosed(False)
    assert application.platformName() == "windows"
    assert application.style().objectName() == "windows11"
    warnings = []
    previous = qInstallMessageHandler(lambda _kind, _context, message: warnings.append(message))

    def process_events():
        loop = QEventLoop()
        QTimer.singleShot(50, loop.quit)
        loop.exec()

    try:
        for language in available_languages():
            set_language(language)
            window = sample_window()
            window._config = replace(window._config, confirm_discard_changes=lambda: True)
            dialog = None
            try:
                assert window.refresh()
                if kind == "analytics_dialog":
                    dialog = AnalyticsDialog(window._analytics_workflow.view_model, date(2026, 5, 14), window)
                    assert dialog.refresh()
                    combo = getattr(dialog, name)
                elif kind == "identity_dialog":
                    handlers = FakeIdentityHandlers()
                    model = IdentityManagementViewModel(
                        user_id=1, list_handler=handlers, providers_handler=handlers,
                        link_handler=handlers, unlink_handler=handlers,
                    )
                    dialog = IdentityDialog(model, window)
                    assert dialog.refresh()
                    combo = dialog.provider_combo
                elif kind == "file_dialog":
                    dialog = QFileDialog(window)
                    dialog.setOption(QFileDialog.Option.DontUseNativeDialog)
                    dialog.setNameFilters(["CSV files (*.csv)", "PDF files (*.pdf)"])
                    combo = dialog.findChild(QComboBox, name)
                else:
                    assert window._switch_route(kind)
                    combo = window.findChild(QComboBox, name)
                assert combo is not None, (kind, name)
                window.show()
                if dialog is not None:
                    dialog.show()
                for dark in (False, True):
                    window._config = replace(window._config, dark=dark)
                    window.apply_theme()
                    process_events()
                    assert combo.isVisible() and combo.isEnabled(), (kind, name)
                    index = combo.currentIndex()
                    data = combo.currentData()
                    option = QStyleOptionComboBox()
                    combo.initStyleOption(option)
                    arrow = combo.style().subControlRect(
                        QStyle.ComplexControl.CC_ComboBox, option,
                        QStyle.SubControl.SC_ComboBoxArrow, combo,
                    )
                    QTest.mouseClick(combo, Qt.MouseButton.LeftButton, pos=arrow.center())
                    process_events()
                    assert combo.view().isVisible(), (kind, name, language, dark)
                    screenshots = os.environ.get("WORKLOGGER_SCREENSHOTS")
                    if screenshots:
                        directory = Path(screenshots)
                        directory.mkdir(parents=True, exist_ok=True)
                        destination = directory / f"native-{language}-{name}-{'dark' if dark else 'light'}.png"
                        assert combo.view().window().grab().save(str(destination))
                    QTest.keyClick(combo.view(), Qt.Key.Key_Escape)
                    process_events()
                    assert not combo.view().isVisible(), (kind, name)
                    assert (combo.currentIndex(), combo.currentData()) == (index, data)
                    assert not [message for message in warnings if "QFont::" in message], warnings
            finally:
                if dialog is not None:
                    dialog.close()
                window.close()
                window.deleteLater()
                application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        print(f"{kind}/{name}: five languages, light/dark themes, no QFont warnings.")
    finally:
        qInstallMessageHandler(previous)


@unittest.skipUnless(sys.platform == "win32", "Requires the native Windows Qt platform")
class NativeDropdownTests(unittest.TestCase):
    def test_each_dropdown_renders_without_font_warnings(self):
        for kind, name in DROPDOWNS:
            with self.subTest(kind=kind, control=name):
                environment = dict(os.environ, QT_QPA_PLATFORM="windows", QT_STYLE_OVERRIDE="windows11")
                result = subprocess.run(
                    [sys.executable, "-m", "tests.presentation.test_native_dropdowns", "--native-dropdown-check", kind, name],
                    cwd=Path(__file__).resolve().parents[2], env=environment,
                    capture_output=True, text=True, timeout=90,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    if "--native-dropdown-check" in sys.argv:
        check_dropdown(sys.argv[-2], sys.argv[-1])
    else:
        unittest.main()
