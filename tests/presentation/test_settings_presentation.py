from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from dataclasses import replace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit

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
    NETWORK_PROXY_PORT_SETTING_KEY,
)
from worklogger.domain.auth.models import User
from worklogger.infrastructure.i18n import available_languages, get_language, set_language
from worklogger.presentation.settings import SettingsDialog, SettingsPage
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
    def test_language_options_always_use_native_labels_and_keep_language_codes(self):
        expected = ("English", "日本語", "한국어", "简体中文", "繁體中文")
        try:
            for language in available_languages():
                set_language(language)
                page = SettingsPage(_view_model(MemorySettingsRepository()))
                page.refresh()
                self.assertEqual(tuple(page.language_combo.itemText(index) for index in range(5)), expected)
                self.assertEqual(tuple(page.language_combo.itemData(index) for index in range(5)), available_languages())
                self.assertEqual(get_language(), language)
                page.close()
        finally:
            set_language("en_US")

    def test_appearance_fields_and_color_picker_use_current_color(self):
        model = _view_model(MemorySettingsRepository())
        model.set_custom_color("#123456")
        page = SettingsPage(model)
        page.refresh()
        self.assertEqual(page.language_combo.width(), page.theme_combo.width())
        self.assertEqual(page.mode_combo.width(), page.theme_combo.width())
        self.assertEqual(page.custom_color_button.icon().pixmap(20, 20).toImage().pixelColor(10, 10).name(), "#123456")
        with patch("worklogger.presentation.settings.page.QColorDialog.getColor", return_value=QColor()) as choose:
            page._choose_custom_color()
            self.assertEqual(choose.call_args.args[0].name(), "#123456")

    def test_account_uses_login_id_and_action_icons_and_admin_permissions(self):
        page = SettingsPage(_view_model(MemorySettingsRepository()))
        page.set_account(User(id=42, username="alice", is_admin=True))
        self.assertEqual(page.current_user_id_line_edit.text(), "alice")
        self.assertFalse(page.manage_users_button.isHidden())
        for button in (page.change_password_button, page.manage_users_button, page.logout_button,
                       page.manage_identities_button, page.export_csv_button, page.import_csv_button,
                       page.backup_button, page.restore_button, page.import_ics_button, page.export_ics_button):
            self.assertFalse(button.icon().isNull())
        page.set_account(User(id=42, username="alice", is_admin=False))
        self.assertTrue(page.manage_users_button.isHidden())
        self.assertFalse(page.manage_users_button.isEnabled())

    def test_invalid_port_keeps_saved_value_and_has_visible_error(self):
        repository = MemorySettingsRepository()
        page = SettingsPage(_view_model(repository))
        page.refresh()
        page.proxy_port_line_edit.setText("8080")
        page.proxy_port_line_edit.editingFinished.emit()
        page.proxy_port_line_edit.setText("70000")
        page.proxy_port_line_edit.editingFinished.emit()
        self.assertEqual(repository.get(1, NETWORK_PROXY_PORT_SETTING_KEY), "8080")
        self.assertEqual(page.proxy_port_line_edit.text(), "70000")
        self.assertEqual(page.status_label.text(), "Enter a port between 0 and 65535.")
        self.assertFalse(page.status_label.isHidden())

    def test_proxy_password_visibility_respects_storage_availability(self):
        model = _view_model(MemorySettingsRepository())
        page = SettingsPage(model)
        page.refresh()
        self.assertFalse(page.proxy_password_line_edit.isEnabled())
        self.assertFalse(page.proxy_password_visibility_action.isEnabled())
        page.set_state(replace(model.load().value, proxy_password_available=True,
                               network_proxy_password=" synthetic password "))
        self.assertEqual(page.proxy_password_line_edit.text(), " synthetic password ")
        page.proxy_password_visibility_action.trigger()
        self.assertEqual(page.proxy_password_line_edit.echoMode(), QLineEdit.EchoMode.Normal)
        page.proxy_password_visibility_action.trigger()
        self.assertEqual(page.proxy_password_line_edit.echoMode(), QLineEdit.EchoMode.Password)

    def test_backup_and_update_feedback_is_inline_without_duplicate_footer(self):
        page = SettingsPage(_view_model(MemorySettingsRepository()))
        page.refresh()
        self.assertTrue(page.status_label.isHidden())
        page.set_backup_time((datetime.now(timezone.utc) - timedelta(days=45)).isoformat())
        self.assertIn("45 days", page.backup_status_label.text())
        page.set_operation_status("Checking for updates...", "update")
        self.assertEqual(page.update_status_label.text(), "Checking for updates...")
        self.assertFalse(page.update_status_label.isHidden())
        self.assertTrue(page.status_label.isHidden())
        page.set_operation_status("Backing up data...", "data")
        self.assertEqual(page.data_status_label.text(), "Backing up data...")
        self.assertFalse(page.data_status_label.isHidden())

    def test_local_model_enabled_preference_does_not_claim_unavailable_model_is_ready(self):
        page = SettingsPage(_view_model(MemorySettingsRepository()))
        page.refresh()
        self.assertIn("unavailable", page.local_model_status_label.text())
        page.set_local_model_status(ready=True, name="Verified model")
        self.assertIn("Verified model", page.local_model_status_label.text())
        page.local_model_enabled_switch.set_checked(False)
        self.assertEqual(page.local_model_status_label.text(), "Local model disabled.")

    def test_native_settings_expose_unavailable_features_and_busy_state(self) -> None:
        page = SettingsPage(_view_model(MemorySettingsRepository()))
        self.assertFalse(page.external_api_key_line_edit.isEnabled())
        self.assertFalse(page.test_external_model_button.isEnabled())
        self.assertTrue(page.external_model_status_label.text())
        self.assertFalse(page.clear_calendar_events_button.isEnabled())
        self.assertTrue(page.clear_calendar_events_button.toolTip())
        page.set_busy("data", True)
        page.set_busy("update", True)
        page.set_busy("data", False)
        self.assertTrue(page.is_busy)
        self.assertFalse(page.category_stack.isEnabled())
        page.set_busy("update", False)
        self.assertFalse(page.is_busy)
        self.assertTrue(page.category_stack.isEnabled())

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
        self.assertIsInstance(dialog.page, SettingsPage)
        self.assertEqual(set(dialog.page._category_pages), {"appearance", "general", "ai", "data", "network", "account", "about"})

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


    def test_settings_page_is_native_widget_and_switches_categories(self) -> None:
        page = SettingsPage(_view_model(MemorySettingsRepository()))

        self.assertNotIsInstance(page, QDialog)
        self.assertFalse(hasattr(page, "tabs"))
        self.assertFalse(hasattr(page, "close_button"))
        self.assertTrue(page.refresh())

        page.category_nav.set_category("network")

        self.assertEqual(page.category_nav.category, "network")
        self.assertEqual(page.category_stack.currentIndex(), page._category_pages["network"])

    def test_settings_page_emits_data_account_and_about_actions(self) -> None:
        page = SettingsPage(_view_model(MemorySettingsRepository()))
        emitted: list[str] = []
        page.export_csv_requested.connect(lambda: emitted.append("csv"))
        page.import_csv_requested.connect(lambda: emitted.append("import_csv"))
        page.change_password_requested.connect(lambda: emitted.append("password"))
        page.manage_identities_requested.connect(lambda: emitted.append("identities"))
        page.update_check_requested.connect(lambda: emitted.append("updates"))

        page.export_csv_button.click()
        page.import_csv_button.click()
        page.change_password_button.click()
        page.manage_identities_button.click()
        page.check_updates_button.click()

        self.assertEqual(emitted, ["csv", "import_csv", "password", "identities", "updates"])
        self.assertEqual(page.about_name_label.text(), "WorkLogger")
        self.assertIn("4.0.0", page.about_version_label.text())

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
