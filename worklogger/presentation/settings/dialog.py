"""Settings dialog foundation."""

from __future__ import annotations

import sys

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from worklogger.__about__ import APP_AUTHOR, APP_NAME, APP_VERSION, GITHUB_URL
from worklogger.config.constants import (
    AI_ASSIST_ENABLED_SETTING_KEY,
    AI_PRIVACY_INCLUDE_CALENDAR_SETTING_KEY,
    AI_PRIVACY_INCLUDE_NOTES_SETTING_KEY,
    AI_PRIVACY_INCLUDE_QUICK_LOGS_SETTING_KEY,
    DARK_MODE_SETTING_KEY,
    DEFAULT_BREAK_HOURS_SETTING_KEY,
    ENABLE_MENU_BAR_SETTING_KEY,
    ENABLE_TRAY_SETTING_KEY,
    LOCAL_MODEL_ENABLED_SETTING_KEY,
    MINIMAL_MODE_SETTING_KEY,
    MONTHLY_TARGET_HOURS_SETTING_KEY,
    SHOW_HOLIDAYS_SETTING_KEY,
    SHOW_NOTE_MARKERS_SETTING_KEY,
    SHOW_OVERNIGHT_INDICATOR_SETTING_KEY,
    STANDARD_WORK_HOURS_SETTING_KEY,
    WEEK_START_MONDAY_SETTING_KEY,
)
from worklogger.domain.shared.errors import AppError
from worklogger.infrastructure.i18n import _
from worklogger.presentation.viewmodels import SettingsState, SettingsViewModel
from worklogger.presentation.widgets import SwitchButton


class SettingsDialog(QDialog):
    backup_requested = Signal()
    change_password_requested = Signal()
    export_csv_requested = Signal()
    export_ics_requested = Signal()
    import_csv_requested = Signal()
    import_ics_requested = Signal()
    manage_identities_requested = Signal()
    manage_local_models_requested = Signal()
    manage_users_requested = Signal()
    restore_requested = Signal()
    update_check_requested = Signal()

    def __init__(
        self,
        view_model: SettingsViewModel,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._view_model = view_model
        self._updating = False
        self._last_error: AppError | None = None
        self._residency_key = _residency_setting_key()
        self.setObjectName("settings_dialog")
        self.setWindowTitle(_("Settings"))
        self._build_ui()

    @property
    def last_error(self) -> AppError | None:
        return self._last_error

    def refresh(self) -> bool:
        result = self._view_model.load()
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return False
        self.set_state(result.value)
        self.status_label.setText(_("Ready"))
        return True

    def set_state(self, state: SettingsState) -> None:
        self._updating = True
        try:
            theme_index = self.theme_combo.findData(state.theme)
            self.theme_combo.setCurrentIndex(theme_index if theme_index >= 0 else 0)
            self.dark_switch.set_checked(state.dark_mode)
            self.minimal_switch.set_checked(state.minimal_mode)
            self.ai_enabled_switch.set_checked(state.ai_assist_enabled)
            self.ai_notes_switch.set_checked(state.ai_privacy_include_notes)
            self.ai_calendar_switch.set_checked(state.ai_privacy_include_calendar)
            self.ai_quick_logs_switch.set_checked(state.ai_privacy_include_quick_logs)
            self.local_model_enabled_switch.set_checked(state.local_model_enabled)
            self.standard_hours_input.setValue(state.standard_work_hours)
            self.default_break_input.setValue(state.default_break_hours)
            self.monthly_target_input.setValue(state.monthly_target_hours)
            self.holidays_switch.set_checked(state.show_holidays)
            self.note_markers_switch.set_checked(state.show_note_markers)
            self.overnight_switch.set_checked(state.show_overnight_indicator)
            self.week_start_switch.set_checked(state.week_start_monday)
            if self.residency_switch is not None:
                self.residency_switch.set_checked(
                    state.enable_tray
                    if self._residency_key == ENABLE_TRAY_SETTING_KEY
                    else state.enable_menu_bar
                )
        finally:
            self._updating = False

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_appearance_tab(), _("Appearance"))
        self.tabs.addTab(self._build_general_tab(), _("General"))
        self.tabs.addTab(self._build_data_tab(), _("Data"))
        self.tabs.addTab(self._build_account_tab(), _("Account"))
        self.tabs.addTab(self._build_ai_tab(), _("AI"))
        self.tabs.addTab(self._build_local_models_tab(), _("Local Models"))
        self.tabs.addTab(self._build_about_tab(), _("About"))
        root.addWidget(self.tabs)

        bottom = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setObjectName("settings_status_label")
        self.close_button = QPushButton(_("Close"))
        self.close_button.setObjectName("close_settings_button")
        self.close_button.setProperty("variant", "primary")
        self.close_button.clicked.connect(self.accept)
        bottom.addWidget(self.status_label, 1)
        bottom.addWidget(self.close_button)
        root.addLayout(bottom)

    def _build_appearance_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setContentsMargins(12, 12, 12, 12)
        form.setSpacing(10)

        self.theme_combo = QComboBox()
        self.theme_combo.setObjectName("theme_combo")
        for key, label in (
            ("blue", _("Blue")),
            ("pink", _("Pink")),
            ("green", _("Green")),
            ("purple", _("Purple")),
            ("custom", _("Custom")),
        ):
            self.theme_combo.addItem(label, key)
        self.theme_combo.currentIndexChanged.connect(self._theme_changed)
        form.addRow(_("Theme"), self.theme_combo)

        self.dark_switch = SwitchButton()
        self.dark_switch.toggled.connect(
            lambda enabled: self._set_bool(DARK_MODE_SETTING_KEY, enabled)
        )
        form.addRow(_("Dark mode"), _switch_row(self.dark_switch))

        self.minimal_switch = SwitchButton()
        self.minimal_switch.toggled.connect(
            lambda enabled: self._set_bool(MINIMAL_MODE_SETTING_KEY, enabled)
        )
        form.addRow(_("Minimal mode"), _switch_row(self.minimal_switch))
        return tab

    def _build_general_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setContentsMargins(12, 12, 12, 12)
        form.setSpacing(10)

        self.standard_hours_input = _hours_input(1.0, 24.0, 0.5)
        self.standard_hours_input.valueChanged.connect(
            lambda value: self._set_number(STANDARD_WORK_HOURS_SETTING_KEY, value)
        )
        form.addRow(_("Standard hours (h)"), self.standard_hours_input)

        self.default_break_input = _hours_input(0.0, 4.0, 0.25)
        self.default_break_input.valueChanged.connect(
            lambda value: self._set_number(DEFAULT_BREAK_HOURS_SETTING_KEY, value)
        )
        form.addRow(_("Default break (h)"), self.default_break_input)

        self.monthly_target_input = _hours_input(0.0, 400.0, 8.0)
        self.monthly_target_input.valueChanged.connect(
            lambda value: self._set_number(MONTHLY_TARGET_HOURS_SETTING_KEY, value)
        )
        form.addRow(_("Monthly target (h)"), self.monthly_target_input)

        self.holidays_switch = SwitchButton()
        self.holidays_switch.toggled.connect(
            lambda enabled: self._set_bool(SHOW_HOLIDAYS_SETTING_KEY, enabled)
        )
        form.addRow(_("Public holidays"), _switch_row(self.holidays_switch))

        self.note_markers_switch = SwitchButton()
        self.note_markers_switch.toggled.connect(
            lambda enabled: self._set_bool(SHOW_NOTE_MARKERS_SETTING_KEY, enabled)
        )
        form.addRow(_("Notes reminder dot"), _switch_row(self.note_markers_switch))

        self.overnight_switch = SwitchButton()
        self.overnight_switch.toggled.connect(
            lambda enabled: self._set_bool(SHOW_OVERNIGHT_INDICATOR_SETTING_KEY, enabled)
        )
        form.addRow(_("Overnight indicator"), _switch_row(self.overnight_switch))

        self.week_start_switch = SwitchButton()
        self.week_start_switch.toggled.connect(
            lambda enabled: self._set_bool(WEEK_START_MONDAY_SETTING_KEY, enabled)
        )
        form.addRow(_("Start week on Monday"), _switch_row(self.week_start_switch))

        self.residency_switch: SwitchButton | None = None
        if self._residency_key:
            self.residency_switch = SwitchButton()
            self.residency_switch.toggled.connect(
                lambda enabled: self._set_bool(str(self._residency_key), enabled)
            )
            label = (
                _("Enable tray")
                if self._residency_key == ENABLE_TRAY_SETTING_KEY
                else _("Enable menu bar")
            )
            form.addRow(label, _switch_row(self.residency_switch))
        return tab

    def _build_data_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.export_csv_button = QPushButton(_("Export CSV"))
        self.export_csv_button.clicked.connect(self.export_csv_requested.emit)
        self.import_csv_button = QPushButton(_("Import CSV"))
        self.import_csv_button.clicked.connect(self.import_csv_requested.emit)
        self.import_ics_button = QPushButton(_("Import .ics"))
        self.import_ics_button.clicked.connect(self.import_ics_requested.emit)
        self.export_ics_button = QPushButton(_("Export .ics"))
        self.export_ics_button.clicked.connect(self.export_ics_requested.emit)
        self.backup_button = QPushButton(_("Backup Data"))
        self.backup_button.clicked.connect(self.backup_requested.emit)
        self.restore_button = QPushButton(_("Restore Data"))
        self.restore_button.clicked.connect(self.restore_requested.emit)

        layout.addWidget(self.export_csv_button)
        layout.addWidget(self.import_csv_button)
        layout.addWidget(self.import_ics_button)
        layout.addWidget(self.export_ics_button)
        layout.addWidget(self.backup_button)
        layout.addWidget(self.restore_button)
        layout.addStretch(1)
        return tab

    def _build_ai_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setContentsMargins(12, 12, 12, 12)
        form.setSpacing(10)

        self.ai_enabled_switch = SwitchButton()
        self.ai_enabled_switch.toggled.connect(
            lambda enabled: self._set_bool(AI_ASSIST_ENABLED_SETTING_KEY, enabled)
        )
        form.addRow(_("AI Assist"), _switch_row(self.ai_enabled_switch))

        self.ai_notes_switch = SwitchButton()
        self.ai_notes_switch.toggled.connect(
            lambda enabled: self._set_bool(AI_PRIVACY_INCLUDE_NOTES_SETTING_KEY, enabled)
        )
        form.addRow(_("Include notes"), _switch_row(self.ai_notes_switch))

        self.ai_calendar_switch = SwitchButton()
        self.ai_calendar_switch.toggled.connect(
            lambda enabled: self._set_bool(AI_PRIVACY_INCLUDE_CALENDAR_SETTING_KEY, enabled)
        )
        form.addRow(_("Include calendar"), _switch_row(self.ai_calendar_switch))

        self.ai_quick_logs_switch = SwitchButton()
        self.ai_quick_logs_switch.toggled.connect(
            lambda enabled: self._set_bool(AI_PRIVACY_INCLUDE_QUICK_LOGS_SETTING_KEY, enabled)
        )
        form.addRow(_("Include quick logs"), _switch_row(self.ai_quick_logs_switch))
        return tab

    def _build_local_models_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        self.local_model_enabled_switch = SwitchButton()
        self.local_model_enabled_switch.toggled.connect(
            lambda enabled: self._set_bool(LOCAL_MODEL_ENABLED_SETTING_KEY, enabled)
        )
        row_layout.addWidget(QLabel(_("Enable local models")))
        row_layout.addStretch(1)
        row_layout.addWidget(self.local_model_enabled_switch)
        layout.addWidget(row)

        self.local_model_status_label = QLabel(_("Manage downloaded and imported GGUF models."))
        self.local_model_status_label.setObjectName("local_model_status_label")
        self.local_model_status_label.setWordWrap(True)
        self.manage_local_models_button = QPushButton(_("Manage models"))
        self.manage_local_models_button.clicked.connect(
            self.manage_local_models_requested.emit
        )
        layout.addWidget(self.local_model_status_label)
        layout.addWidget(self.manage_local_models_button)
        layout.addStretch(1)
        return tab

    def _build_about_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.about_name_label = QLabel(APP_NAME)
        self.about_name_label.setObjectName("about_name_label")
        self.about_version_label = QLabel(_("Version {version}").format(version=APP_VERSION))
        self.about_author_label = QLabel(_("Author: {author}").format(author=APP_AUTHOR))
        self.about_url_label = QLabel(GITHUB_URL)
        self.about_url_label.setObjectName("about_url_label")
        self.check_updates_button = QPushButton(_("Check for updates"))
        self.check_updates_button.clicked.connect(self.update_check_requested.emit)
        layout.addWidget(self.about_name_label)
        layout.addWidget(self.about_version_label)
        layout.addWidget(self.about_author_label)
        layout.addWidget(self.about_url_label)
        layout.addWidget(self.check_updates_button)
        layout.addStretch(1)
        return tab

    def _build_account_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.change_password_button = QPushButton(_("Change password"))
        self.change_password_button.setObjectName("change_password_button")
        self.change_password_button.setProperty("variant", "primary")
        self.change_password_button.clicked.connect(self.change_password_requested.emit)
        self.manage_users_button = QPushButton(_("Manage users"))
        self.manage_users_button.clicked.connect(self.manage_users_requested.emit)
        self.manage_identities_button = QPushButton(_("Linked identities"))
        self.manage_identities_button.clicked.connect(
            self.manage_identities_requested.emit
        )
        layout.addWidget(self.change_password_button)
        layout.addWidget(self.manage_users_button)
        layout.addWidget(self.manage_identities_button)
        layout.addStretch(1)
        return tab

    def _theme_changed(self) -> None:
        if self._updating:
            return
        result = self._view_model.set_theme(str(self.theme_combo.currentData() or "blue"))
        self._handle_save_result(result)

    def _set_bool(self, key: str, enabled: bool) -> None:
        if self._updating:
            return
        self._handle_save_result(self._view_model.set_bool(key, enabled))

    def _set_number(self, key: str, value: float) -> None:
        if self._updating:
            return
        self._handle_save_result(self._view_model.set_number(key, float(value)))

    def _handle_save_result(self, result: object) -> None:
        if not getattr(result, "ok", False):
            self._set_error(getattr(result, "error", None))
            return
        self.status_label.setText(_("Saved"))

    def _set_error(self, error: AppError | None) -> None:
        self._last_error = error
        self.status_label.setText(error.message if error else _("Unknown error"))


def _switch_row(switch: SwitchButton) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(switch)
    layout.addStretch(1)
    return row


def _hours_input(minimum: float, maximum: float, step: float) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setDecimals(2)
    spin.setRange(minimum, maximum)
    spin.setSingleStep(step)
    spin.setFixedWidth(120)
    return spin


def _residency_setting_key() -> str | None:
    if sys.platform.startswith("win"):
        return ENABLE_TRAY_SETTING_KEY
    if sys.platform == "darwin":
        return ENABLE_MENU_BAR_SETTING_KEY
    return None
