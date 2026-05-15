from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from worklogger.app.use_cases.settings import GetSettingHandler, SetSettingHandler
from worklogger.config.constants import (
    AI_ASSIST_ENABLED_SETTING_KEY,
    AI_PRIVACY_INCLUDE_CALENDAR_SETTING_KEY,
    DARK_MODE_SETTING_KEY,
    DEFAULT_BREAK_HOURS_SETTING_KEY,
    ENABLE_MENU_BAR_SETTING_KEY,
    ENABLE_TRAY_SETTING_KEY,
    LOCAL_MODEL_ENABLED_SETTING_KEY,
    MINIMAL_MODE_SETTING_KEY,
    MONTHLY_TARGET_HOURS_SETTING_KEY,
    SHOW_HOLIDAYS_SETTING_KEY,
    STANDARD_WORK_HOURS_SETTING_KEY,
    THEME_SETTING_KEY,
)
from worklogger.presentation.settings import SettingsDialog
from worklogger.presentation.viewmodels import SettingsViewModel
from worklogger.presentation.widgets import SwitchButton


def _app() -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        return existing
    return QApplication([])


class MemorySettingsRepository:
    def __init__(self) -> None:
        self.values: dict[tuple[int, str], str] = {}

    def get(self, user_id: int, key: str, default: str | None = None) -> str | None:
        return self.values.get((user_id, key), default)

    def set(self, user_id: int, key: str, value: str) -> None:
        self.values[(user_id, key)] = value

    def delete(self, user_id: int, key: str) -> None:
        self.values.pop((user_id, key), None)


def _view_model(repository: MemorySettingsRepository) -> SettingsViewModel:
    return SettingsViewModel(
        user_id=1,
        get_handler=GetSettingHandler(repository),
        set_handler=SetSettingHandler(repository),
    )


class SettingsPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = _app()

    def test_switch_button_tracks_checked_state_and_emits_toggled(self) -> None:
        switch = SwitchButton(checked=False)
        toggles: list[bool] = []
        switch.toggled.connect(toggles.append)

        switch.set_checked(True)
        switch.set_checked(True)
        switch.set_checked(False)

        self.assertEqual(toggles, [True, False])
        self.assertFalse(switch.is_checked())

    def test_settings_viewmodel_loads_defaults_and_persists_changes(self) -> None:
        repository = MemorySettingsRepository()
        view_model = _view_model(repository)

        loaded = view_model.load()

        self.assertTrue(loaded.ok, loaded.error)
        assert loaded.value is not None
        self.assertEqual(loaded.value.theme, "blue")
        self.assertFalse(loaded.value.dark_mode)
        self.assertTrue(loaded.value.show_holidays)
        self.assertEqual(loaded.value.standard_work_hours, 8.0)

        self.assertTrue(view_model.set_theme("green").ok)
        self.assertTrue(view_model.set_bool(DARK_MODE_SETTING_KEY, True).ok)
        self.assertTrue(view_model.set_number(STANDARD_WORK_HOURS_SETTING_KEY, 7.5).ok)

        reloaded = view_model.load()

        self.assertTrue(reloaded.ok, reloaded.error)
        assert reloaded.value is not None
        self.assertEqual(reloaded.value.theme, "green")
        self.assertTrue(reloaded.value.dark_mode)
        self.assertEqual(reloaded.value.standard_work_hours, 7.5)
        self.assertEqual(repository.values[(1, THEME_SETTING_KEY)], "green")
        self.assertEqual(repository.values[(1, DARK_MODE_SETTING_KEY)], "1")

    def test_settings_dialog_binds_controls_to_viewmodel(self) -> None:
        repository = MemorySettingsRepository()
        repository.set(1, THEME_SETTING_KEY, "pink")
        repository.set(1, DARK_MODE_SETTING_KEY, "1")
        repository.set(1, MINIMAL_MODE_SETTING_KEY, "0")
        repository.set(1, STANDARD_WORK_HOURS_SETTING_KEY, "7.5")
        repository.set(1, DEFAULT_BREAK_HOURS_SETTING_KEY, "0.5")
        repository.set(1, MONTHLY_TARGET_HOURS_SETTING_KEY, "120")
        repository.set(1, SHOW_HOLIDAYS_SETTING_KEY, "1")
        dialog = SettingsDialog(_view_model(repository))

        self.assertTrue(dialog.refresh())
        self.assertEqual(dialog.theme_combo.currentData(), "pink")
        self.assertTrue(dialog.dark_switch.is_checked())
        self.assertEqual(dialog.standard_hours_input.value(), 7.5)

        dialog.theme_combo.setCurrentIndex(dialog.theme_combo.findData("green"))
        dialog.dark_switch.set_checked(False)
        dialog.standard_hours_input.setValue(8.5)
        if dialog.residency_switch is not None:
            dialog.residency_switch.set_checked(True)
            residency_key = (
                ENABLE_TRAY_SETTING_KEY
                if sys.platform.startswith("win")
                else ENABLE_MENU_BAR_SETTING_KEY
            )
            self.assertEqual(repository.values[(1, residency_key)], "1")

        self.assertEqual(repository.values[(1, THEME_SETTING_KEY)], "green")
        self.assertEqual(repository.values[(1, DARK_MODE_SETTING_KEY)], "0")
        self.assertEqual(repository.values[(1, STANDARD_WORK_HOURS_SETTING_KEY)], "8.5")
        self.assertEqual(dialog.status_label.text(), "Saved")

    def test_settings_dialog_exposes_account_change_password_entry(self) -> None:
        repository = MemorySettingsRepository()
        dialog = SettingsDialog(_view_model(repository))
        requests: list[bool] = []
        dialog.change_password_requested.connect(lambda: requests.append(True))

        dialog.change_password_button.click()

        self.assertEqual(requests, [True])

    def test_settings_dialog_exposes_data_management_entries(self) -> None:
        repository = MemorySettingsRepository()
        dialog = SettingsDialog(_view_model(repository))
        emitted: list[str] = []
        dialog.export_csv_requested.connect(lambda: emitted.append("csv"))
        dialog.import_csv_requested.connect(lambda: emitted.append("import_csv"))
        dialog.export_ics_requested.connect(lambda: emitted.append("ics"))
        dialog.backup_requested.connect(lambda: emitted.append("backup"))
        dialog.restore_requested.connect(lambda: emitted.append("restore"))

        dialog.export_csv_button.click()
        dialog.import_csv_button.click()
        dialog.export_ics_button.click()
        dialog.backup_button.click()
        dialog.restore_button.click()

        self.assertEqual(emitted, ["csv", "import_csv", "ics", "backup", "restore"])

    def test_settings_dialog_exposes_ai_local_model_and_about_tabs(self) -> None:
        repository = MemorySettingsRepository()
        dialog = SettingsDialog(_view_model(repository))

        self.assertTrue(dialog.refresh())
        tab_labels = [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())]
        self.assertIn("AI", tab_labels)
        self.assertIn("Local Models", tab_labels)
        self.assertIn("About", tab_labels)

        dialog.ai_enabled_switch.set_checked(False)
        dialog.ai_calendar_switch.set_checked(False)
        dialog.local_model_enabled_switch.set_checked(False)

        self.assertEqual(repository.values[(1, AI_ASSIST_ENABLED_SETTING_KEY)], "0")
        self.assertEqual(
            repository.values[(1, AI_PRIVACY_INCLUDE_CALENDAR_SETTING_KEY)],
            "0",
        )
        self.assertEqual(repository.values[(1, LOCAL_MODEL_ENABLED_SETTING_KEY)], "0")
        self.assertEqual(dialog.about_name_label.text(), "WorkLogger")
        self.assertIn("4.0.0", dialog.about_version_label.text())

    def test_settings_dialog_renders_offscreen(self) -> None:
        dialog = SettingsDialog(_view_model(MemorySettingsRepository()))
        self.assertTrue(dialog.refresh())
        dialog.resize(560, 460)
        dialog.show()
        self._app.processEvents()

        pixmap = dialog.grab()

        self.assertFalse(pixmap.isNull())
        self.assertGreaterEqual(pixmap.width(), 520)
        self.assertGreaterEqual(pixmap.height(), 420)
        dialog.close()


if __name__ == "__main__":
    unittest.main()
