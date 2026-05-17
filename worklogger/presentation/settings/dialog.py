"""Prototype-aligned settings surface."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
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
    CUSTOM_THEME_COLOR_SETTING_KEY,
    DARK_MODE_SETTING_KEY,
    DEFAULT_BREAK_HOURS_SETTING_KEY,
    ENABLE_MENU_BAR_SETTING_KEY,
    ENABLE_TRAY_SETTING_KEY,
    EXTERNAL_MODEL_BASE_URL_SETTING_KEY,
    EXTERNAL_MODEL_NAME_SETTING_KEY,
    LANGUAGE_SETTING_KEY,
    LOCAL_MODEL_ENABLED_SETTING_KEY,
    MINIMAL_MODE_SETTING_KEY,
    MONTHLY_TARGET_HOURS_SETTING_KEY,
    NETWORK_PROXY_ADDRESS_SETTING_KEY,
    NETWORK_PROXY_DOMAIN_SETTING_KEY,
    NETWORK_PROXY_ENABLED_SETTING_KEY,
    NETWORK_PROXY_PASSWORD_SETTING_KEY,
    NETWORK_PROXY_PORT_SETTING_KEY,
    NETWORK_PROXY_USERNAME_SETTING_KEY,
    SHOW_HOLIDAYS_SETTING_KEY,
    SHOW_NOTE_MARKERS_SETTING_KEY,
    SHOW_OVERNIGHT_INDICATOR_SETTING_KEY,
    STANDARD_WORK_HOURS_SETTING_KEY,
    WEEK_START_MONDAY_SETTING_KEY,
)
from worklogger.domain.auth.models import User
from worklogger.domain.shared.errors import AppError
from worklogger.infrastructure.i18n import _, available_languages
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.theme import install_bundled_fonts
from worklogger.presentation.viewmodels import SettingsState, SettingsViewModel
from worklogger.presentation.widgets import CardFrame, SettingsNav, SwitchButton
from worklogger.presentation.widgets.assets import apply_window_icon, pixmap_asset


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
    logout_requested = Signal()
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
        self._category_pages: dict[str, int] = {}
        self.setObjectName("settings_dialog")
        self.setWindowTitle(_("Settings"))
        apply_window_icon(self)
        self.setMinimumSize(880, 580)
        install_bundled_fonts()
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

    def set_account(self, user: User) -> None:
        self.current_user_name_line_edit.setText(user.username)
        self.current_user_id_line_edit.setText(str(user.id))
        self.current_user_role_line_edit.setText(_("Admin") if user.is_admin else _("User"))
        self.set_manage_users_available(user.is_admin)

    def set_manage_users_available(self, available: bool) -> None:
        self.manage_users_button.setVisible(bool(available))
        self.manage_users_button.setEnabled(bool(available))

    def set_state(self, state: SettingsState) -> None:
        self._updating = True
        try:
            language_index = self.language_combo.findData(state.language)
            self.language_combo.setCurrentIndex(language_index if language_index >= 0 else 0)
            theme_index = self.theme_combo.findData(state.theme)
            self.theme_combo.setCurrentIndex(theme_index if theme_index >= 0 else 0)
            mode_index = self.mode_combo.findData("dark" if state.dark_mode else "light")
            self.mode_combo.setCurrentIndex(mode_index if mode_index >= 0 else 0)
            self.dark_switch.set_checked(state.dark_mode)
            self.minimal_switch.set_checked(state.minimal_mode)
            self.ai_enabled_switch.set_checked(state.ai_assist_enabled)
            self.ai_notes_switch.set_checked(state.ai_privacy_include_notes)
            self.ai_calendar_switch.set_checked(state.ai_privacy_include_calendar)
            self.ai_quick_logs_switch.set_checked(state.ai_privacy_include_quick_logs)
            self.external_base_url_line_edit.setText(state.external_model_base_url)
            self.external_model_line_edit.setText(state.external_model_name)
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
            self.proxy_enabled_switch.set_checked(state.network_proxy_enabled)
            self.proxy_address_line_edit.setText(state.network_proxy_address)
            self.proxy_port_line_edit.setText(state.network_proxy_port)
            self.proxy_username_line_edit.setText(state.network_proxy_username)
            self.proxy_password_line_edit.setText(state.network_proxy_password)
            self.proxy_domain_line_edit.setText(state.network_proxy_domain)
        finally:
            self._updating = False

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 18)
        root.setSpacing(16)

        self.tabs = self._compat_tabs()
        self.tabs.setVisible(False)
        root.addWidget(self.tabs)

        title = QLabel(_("Settings"))
        title.setObjectName("settings_title_label")
        title.setProperty("role", "title")
        root.addWidget(title)

        content = QHBoxLayout()
        content.setSpacing(16)
        root.addLayout(content, 1)

        self.category_nav = SettingsNav(
            (
                ("appearance", _("Appearance")),
                ("general", _("General")),
                ("ai", _("AI")),
                ("data", _("Data")),
                ("network", _("Network")),
                ("account", _("Account")),
                ("about", _("About")),
            )
        )
        self.category_nav.setFixedWidth(210)
        self.category_nav.category_changed.connect(self._set_category)
        content.addWidget(self.category_nav)

        self.category_stack = QStackedWidget()
        self.category_stack.setObjectName("settings_category_stack_widget")
        content.addWidget(self.category_stack, 1)
        self._add_category("appearance", self._build_appearance_page())
        self._add_category("general", self._build_general_page())
        self._add_category("ai", self._build_ai_page())
        self._add_category("data", self._build_data_page())
        self._add_category("network", self._build_network_page())
        self._add_category("account", self._build_account_page())
        self._add_category("about", self._build_about_page())

        bottom = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setObjectName("settings_status_label")
        self.status_label.setProperty("role", "secondary")
        self.close_button = QPushButton(_("Close"))
        self.close_button.setObjectName("close_settings_button")
        self.close_button.setProperty("variant", "primary")
        self.close_button.clicked.connect(self.accept)
        bottom.addWidget(self.status_label, 1)
        bottom.addWidget(self.close_button)
        root.addLayout(bottom)

    def _compat_tabs(self) -> QTabWidget:
        tabs = QTabWidget()
        tabs.setObjectName("settings_tabs_tab_widget")
        for label in (
            _("Appearance"),
            _("General"),
            _("Data"),
            _("Account"),
            _("AI"),
            _("Local Models"),
            _("About"),
        ):
            tabs.addTab(QWidget(), label)
        return tabs

    def _add_category(self, key: str, widget: QWidget) -> None:
        self._category_pages[key] = self.category_stack.addWidget(widget)

    def _set_category(self, key: str) -> None:
        index = self._category_pages.get(key)
        if index is not None:
            self.category_stack.setCurrentIndex(index)

    def _build_appearance_page(self) -> QWidget:
        page = self._scroll_page()
        card = _card_with_form(_("Appearance"))
        form = card.form_layout

        self.language_combo = QComboBox()
        self.language_combo.setObjectName("language_combo")
        for language in available_languages():
            self.language_combo.addItem(_language_label(language), language)
        self.language_combo.currentIndexChanged.connect(self._language_changed)
        form.addRow(_("Language"), self.language_combo)

        theme_row = QWidget()
        theme_layout = QHBoxLayout(theme_row)
        theme_layout.setContentsMargins(0, 0, 0, 0)
        theme_layout.setSpacing(10)
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
        self.custom_color_button = QPushButton(_("Palette"))
        self.custom_color_button.setObjectName("custom_color_button")
        self.custom_color_button.clicked.connect(self._choose_custom_color)
        theme_layout.addWidget(self.theme_combo, 1)
        theme_layout.addWidget(self.custom_color_button)
        form.addRow(_("Theme"), theme_row)

        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("mode_combo")
        self.mode_combo.addItem(_("Light mode"), "light")
        self.mode_combo.addItem(_("Dark mode"), "dark")
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        form.addRow(_("Mode"), self.mode_combo)

        self.dark_switch = SwitchButton()
        self.dark_switch.setVisible(False)
        self.dark_switch.toggled.connect(
            lambda enabled: self._set_bool(DARK_MODE_SETTING_KEY, enabled)
        )
        self.minimal_switch = SwitchButton()
        self.minimal_switch.setEnabled(False)
        self.minimal_switch.setVisible(False)
        self.minimal_switch.toggled.connect(
            lambda enabled: self._set_bool(MINIMAL_MODE_SETTING_KEY, enabled)
        )
        page.layout().addWidget(card)
        page.layout().addStretch(1)
        return page

    def _build_general_page(self) -> QWidget:
        page = self._scroll_page()
        card = _card_with_form(_("General"))
        form = card.form_layout

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
        self.note_markers_switch.setVisible(False)
        self.note_markers_switch.toggled.connect(
            lambda enabled: self._set_bool(SHOW_NOTE_MARKERS_SETTING_KEY, enabled)
        )

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
                _("Enable tray icon")
                if self._residency_key == ENABLE_TRAY_SETTING_KEY
                else _("Enable menu bar")
            )
            form.addRow(label, _switch_row(self.residency_switch))
        page.layout().addWidget(card)
        page.layout().addStretch(1)
        return page

    def _build_ai_page(self) -> QWidget:
        page = self._scroll_page()

        external = CardFrame(object_name="settings_content_frame")
        external.content_layout.addWidget(_section_title(_("External Model")))
        external.content_layout.addWidget(
            _secondary_label(
                _("OpenAI-compatible models are supported, including ChatGPT, Claude, Qwen, and DeepSeek.")
            )
        )
        form = QFormLayout()
        form.setSpacing(12)
        self.external_api_key_line_edit = QLineEdit()
        self.external_api_key_line_edit.setObjectName("external_api_key_line_edit")
        self.external_api_key_line_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.external_api_key_line_edit.setPlaceholderText(_("Stored securely in a future update"))
        form.addRow(_("API Key"), self.external_api_key_line_edit)
        self.external_base_url_line_edit = QLineEdit()
        self.external_base_url_line_edit.setObjectName("external_base_url_line_edit")
        self.external_base_url_line_edit.editingFinished.connect(
            lambda: self._set_text(
                EXTERNAL_MODEL_BASE_URL_SETTING_KEY,
                self.external_base_url_line_edit.text(),
            )
        )
        form.addRow(_("API Base URL"), self.external_base_url_line_edit)
        self.external_model_line_edit = QLineEdit()
        self.external_model_line_edit.setObjectName("external_model_line_edit")
        self.external_model_line_edit.editingFinished.connect(
            lambda: self._set_text(EXTERNAL_MODEL_NAME_SETTING_KEY, self.external_model_line_edit.text())
        )
        form.addRow(_("Model"), self.external_model_line_edit)
        external.content_layout.addLayout(form)
        self.test_external_model_button = QPushButton(_("Test"))
        self.test_external_model_button.setObjectName("test_external_model_button")
        self.test_external_model_button.clicked.connect(self._mark_external_test_unconfigured)
        self.external_model_status_label = _secondary_label("")
        self.external_model_status_label.setObjectName("external_model_status_label")
        external.content_layout.addWidget(self.test_external_model_button, 0, Qt.AlignmentFlag.AlignLeft)
        external.content_layout.addWidget(self.external_model_status_label)
        page.layout().addWidget(external)

        local = CardFrame(object_name="settings_content_frame")
        local.content_layout.addWidget(_section_title(_("Local Model")))
        local_row = QHBoxLayout()
        local_row.setContentsMargins(0, 0, 0, 0)
        local_row.addWidget(QLabel(_("Enable local model")))
        local_row.addStretch(1)
        self.local_model_enabled_switch = SwitchButton()
        self.local_model_enabled_switch.toggled.connect(
            lambda enabled: self._set_bool(LOCAL_MODEL_ENABLED_SETTING_KEY, enabled)
        )
        local_row.addWidget(self.local_model_enabled_switch)
        local.content_layout.addLayout(local_row)
        local.content_layout.addWidget(
            _secondary_label(
                _("When enabled, text processing uses the local model first; no data is sent to external services.")
            )
        )
        self.local_model_status_label = QLabel(_("Manage downloaded and imported GGUF models."))
        self.local_model_status_label.setObjectName("local_model_status_label")
        self.local_model_status_label.setProperty("role", "secondary")
        local.content_layout.addWidget(self.local_model_status_label)
        self.manage_local_models_button = QPushButton(_("Manage models"))
        self.manage_local_models_button.setObjectName("manage_local_models_button")
        self.manage_local_models_button.clicked.connect(self.manage_local_models_requested.emit)
        local.content_layout.addWidget(self.manage_local_models_button, 0, Qt.AlignmentFlag.AlignLeft)
        page.layout().addWidget(local)

        privacy = CardFrame(object_name="settings_content_frame")
        privacy.content_layout.addWidget(_section_title(_("AI Privacy")))
        self.ai_enabled_switch = SwitchButton()
        self.ai_enabled_switch.toggled.connect(
            lambda enabled: self._set_bool(AI_ASSIST_ENABLED_SETTING_KEY, enabled)
        )
        privacy.content_layout.addWidget(_switch_line(_("AI Assist"), self.ai_enabled_switch))
        self.ai_notes_switch = SwitchButton()
        self.ai_notes_switch.toggled.connect(
            lambda enabled: self._set_bool(AI_PRIVACY_INCLUDE_NOTES_SETTING_KEY, enabled)
        )
        privacy.content_layout.addWidget(_switch_line(_("Include notes"), self.ai_notes_switch))
        self.ai_calendar_switch = SwitchButton()
        self.ai_calendar_switch.toggled.connect(
            lambda enabled: self._set_bool(AI_PRIVACY_INCLUDE_CALENDAR_SETTING_KEY, enabled)
        )
        privacy.content_layout.addWidget(_switch_line(_("Include calendar"), self.ai_calendar_switch))
        self.ai_quick_logs_switch = SwitchButton()
        self.ai_quick_logs_switch.toggled.connect(
            lambda enabled: self._set_bool(AI_PRIVACY_INCLUDE_QUICK_LOGS_SETTING_KEY, enabled)
        )
        privacy.content_layout.addWidget(_switch_line(_("Include quick logs"), self.ai_quick_logs_switch))
        page.layout().addWidget(privacy)
        page.layout().addStretch(1)
        return page

    def _build_data_page(self) -> QWidget:
        page = self._scroll_page()
        csv_card = _action_card(
            _("CSV Data Management"),
            _("Import or export worklog records as CSV files for backup, migration, or spreadsheet analysis."),
        )
        self.export_csv_button = QPushButton(_("Export CSV"))
        self.export_csv_button.setObjectName("export_csv_button")
        self.export_csv_button.setProperty("variant", "outline")
        self.export_csv_button.clicked.connect(self.export_csv_requested.emit)
        self.import_csv_button = QPushButton(_("Import CSV"))
        self.import_csv_button.setObjectName("import_csv_button")
        self.import_csv_button.setProperty("variant", "outline")
        self.import_csv_button.clicked.connect(self.import_csv_requested.emit)
        _add_action_buttons(csv_card, self.export_csv_button, self.import_csv_button)
        page.layout().addWidget(csv_card)

        backup_card = _action_card(
            _("Database Backup"),
            _("Back up your database regularly to protect your local work logs, reports, settings, and account data."),
        )
        self.backup_button = QPushButton(_("Backup Data"))
        self.backup_button.setObjectName("backup_button")
        self.backup_button.setProperty("variant", "outline")
        self.backup_button.clicked.connect(self.backup_requested.emit)
        self.restore_button = QPushButton(_("Restore Data"))
        self.restore_button.setObjectName("restore_button")
        self.restore_button.setProperty("variant", "outline")
        self.restore_button.clicked.connect(self.restore_requested.emit)
        _add_action_buttons(backup_card, self.backup_button, self.restore_button)
        backup_card.content_layout.addWidget(
            _secondary_label(_("You haven't backed up in 30 days. Please back up your data."))
        )
        page.layout().addWidget(backup_card)

        calendar_card = _action_card(
            _("Calendar Data"),
            _("Import your .ics file to let AI read your meetings when generating reports."),
        )
        self.import_ics_button = QPushButton(_("Import Calendar (.ics)"))
        self.import_ics_button.setObjectName("import_ics_button")
        self.import_ics_button.setProperty("variant", "outline")
        self.import_ics_button.clicked.connect(self.import_ics_requested.emit)
        self.export_ics_button = QPushButton(_("Export .ics"))
        self.export_ics_button.setObjectName("export_ics_button")
        self.export_ics_button.setProperty("variant", "outline")
        self.export_ics_button.clicked.connect(self.export_ics_requested.emit)
        self.clear_calendar_events_button = QPushButton(_("Clear Calendar Events"))
        self.clear_calendar_events_button.setObjectName("clear_calendar_events_button")
        self.clear_calendar_events_button.setProperty("variant", "outline")
        self.clear_calendar_events_button.setEnabled(False)
        _add_action_buttons(
            calendar_card,
            self.import_ics_button,
            self.export_ics_button,
            self.clear_calendar_events_button,
        )
        page.layout().addWidget(calendar_card)
        page.layout().addStretch(1)
        return page

    def _build_network_page(self) -> QWidget:
        page = self._scroll_page()
        card = CardFrame(object_name="settings_content_frame")
        card.content_layout.addWidget(_section_title(_("Web proxy")))
        self.proxy_enabled_switch = SwitchButton()
        self.proxy_enabled_switch.toggled.connect(
            lambda enabled: self._set_bool(NETWORK_PROXY_ENABLED_SETTING_KEY, enabled)
        )
        card.content_layout.addWidget(_switch_line(_("Use a web proxy for this application."), self.proxy_enabled_switch))
        card.content_layout.addWidget(
            _secondary_label(_("Network proxy settings are saved now; applying them to HTTP requests is a follow-up item."))
        )

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(10)
        self.proxy_address_line_edit = _text_line_edit("network_address_line_edit")
        self.proxy_port_line_edit = _text_line_edit("network_port_line_edit")
        self.proxy_username_line_edit = _text_line_edit("network_username_line_edit")
        self.proxy_password_line_edit = _text_line_edit("network_password_line_edit")
        self.proxy_password_line_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.proxy_domain_line_edit = _text_line_edit("network_domain_line_edit")
        _connect_text(self.proxy_address_line_edit, lambda: self._set_text(NETWORK_PROXY_ADDRESS_SETTING_KEY, self.proxy_address_line_edit.text()))
        _connect_text(self.proxy_port_line_edit, lambda: self._set_text(NETWORK_PROXY_PORT_SETTING_KEY, self.proxy_port_line_edit.text()))
        _connect_text(self.proxy_username_line_edit, lambda: self._set_text(NETWORK_PROXY_USERNAME_SETTING_KEY, self.proxy_username_line_edit.text()))
        _connect_text(self.proxy_password_line_edit, lambda: self._set_text(NETWORK_PROXY_PASSWORD_SETTING_KEY, self.proxy_password_line_edit.text()))
        _connect_text(self.proxy_domain_line_edit, lambda: self._set_text(NETWORK_PROXY_DOMAIN_SETTING_KEY, self.proxy_domain_line_edit.text()))
        grid.addWidget(QLabel(_("Address")), 0, 0)
        grid.addWidget(QLabel(_("Port")), 0, 1)
        grid.addWidget(self.proxy_address_line_edit, 1, 0)
        grid.addWidget(self.proxy_port_line_edit, 1, 1)
        grid.addWidget(_section_title(_("Authentication information (optional)")), 2, 0, 1, 2)
        grid.addWidget(QLabel(_("Username")), 3, 0, 1, 2)
        grid.addWidget(self.proxy_username_line_edit, 4, 0, 1, 2)
        grid.addWidget(QLabel(_("Password")), 5, 0, 1, 2)
        grid.addWidget(self.proxy_password_line_edit, 6, 0, 1, 2)
        grid.addWidget(QLabel(_("Domain")), 7, 0, 1, 2)
        grid.addWidget(self.proxy_domain_line_edit, 8, 0, 1, 2)
        card.content_layout.addLayout(grid)
        page.layout().addWidget(card)
        page.layout().addStretch(1)
        return page

    def _build_account_page(self) -> QWidget:
        page = self._scroll_page()
        card = CardFrame(object_name="settings_content_frame")
        form = QFormLayout()
        form.setSpacing(12)
        self.current_user_name_line_edit = _readonly_line_edit("account_name_line_edit")
        self.current_user_id_line_edit = _readonly_line_edit("account_id_line_edit")
        self.current_user_role_line_edit = _readonly_line_edit("account_role_line_edit")
        form.addRow(_("Current user"), self.current_user_name_line_edit)
        form.addRow(_("Current ID"), self.current_user_id_line_edit)
        form.addRow(_("Role"), self.current_user_role_line_edit)
        card.content_layout.addLayout(form)
        card.content_layout.addWidget(_secondary_label(_("Changing password will reset the recovery key.")))
        self.change_password_button = QPushButton(_("Change password"))
        self.change_password_button.setObjectName("change_password_button")
        self.change_password_button.setProperty("variant", "outline")
        self.change_password_button.clicked.connect(self.change_password_requested.emit)
        self.manage_users_button = QPushButton(_("Manage users"))
        self.manage_users_button.setObjectName("manage_users_button")
        self.manage_users_button.setProperty("variant", "outline")
        self.manage_users_button.clicked.connect(self.manage_users_requested.emit)
        self.logout_button = QPushButton(_("Log Out"))
        self.logout_button.setObjectName("settings_logout_button")
        self.logout_button.setProperty("variant", "outline")
        self.logout_button.clicked.connect(self.logout_requested.emit)
        self.manage_identities_button = QPushButton(_("Linked identities"))
        self.manage_identities_button.setObjectName("manage_identities_button")
        self.manage_identities_button.setProperty("variant", "outline")
        self.manage_identities_button.clicked.connect(self.manage_identities_requested.emit)
        for button in (
            self.change_password_button,
            self.manage_users_button,
            self.logout_button,
            self.manage_identities_button,
        ):
            card.content_layout.addWidget(button)
        page.layout().addWidget(card)
        page.layout().addStretch(1)
        return page

    def _build_about_page(self) -> QWidget:
        page = self._scroll_page()
        card = CardFrame(object_name="settings_content_frame")
        card.content_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        icon = QLabel("")
        icon.setObjectName("about_icon_label")
        pixmap = pixmap_asset("icons/worklogger.webp")
        if not pixmap.isNull():
            icon.setPixmap(pixmap.scaled(120, 120, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.content_layout.addWidget(icon)
        self.about_name_label = QLabel(APP_NAME)
        self.about_name_label.setObjectName("about_name_label")
        self.about_name_label.setProperty("role", "title")
        self.about_name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.about_version_label = QLabel(_("Version {version}").format(version=APP_VERSION))
        self.about_version_label.setObjectName("about_version_label")
        self.about_version_label.setProperty("role", "secondary")
        self.about_version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_brief = QLabel(_("A privacy-first desktop work tracker with AI-powered reporting."))
        about_brief.setObjectName("about_brief_label")
        about_brief.setProperty("role", "secondary")
        about_brief.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.content_layout.addWidget(self.about_name_label)
        card.content_layout.addWidget(self.about_version_label)
        card.content_layout.addWidget(about_brief)
        details = QFormLayout()
        self.about_author_label = QLabel(APP_AUTHOR)
        self.about_author_label.setObjectName("about_author_label")
        self.about_license_label = QLabel(_("GNU GPLv3"))
        self.about_license_label.setObjectName("about_license_label")
        self.about_url_label = QLabel(GITHUB_URL)
        self.about_url_label.setObjectName("about_url_label")
        details.addRow(_("Author"), self.about_author_label)
        details.addRow(_("License"), self.about_license_label)
        details.addRow(_("GitHub"), self.about_url_label)
        card.content_layout.addLayout(details)
        self.check_updates_button = QPushButton(_("Check for updates"))
        self.check_updates_button.setObjectName("check_updates_button")
        self.check_updates_button.setProperty("variant", "outline")
        self.check_updates_button.clicked.connect(self.update_check_requested.emit)
        card.content_layout.addWidget(self.check_updates_button, 0, Qt.AlignmentFlag.AlignHCenter)
        page.layout().addWidget(card)
        page.layout().addStretch(1)
        return page

    def _scroll_page(self) -> QWidget:
        content = QWidget()
        content.setObjectName("settings_scroll_content_widget")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        return content

    def _language_changed(self) -> None:
        if self._updating:
            return
        self._handle_save_result(
            self._view_model.set_language(str(self.language_combo.currentData() or "en_US"))
        )

    def _theme_changed(self) -> None:
        if self._updating:
            return
        result = self._view_model.set_theme(str(self.theme_combo.currentData() or "blue"))
        self._handle_save_result(result)

    def _mode_changed(self) -> None:
        if self._updating:
            return
        mode = str(self.mode_combo.currentData() or "light")
        self._set_bool(DARK_MODE_SETTING_KEY, mode == "dark")

    def _choose_custom_color(self) -> None:
        color = QColorDialog.getColor(QColor("#4f8ef7"), self, _("Choose custom color"))
        if color.isValid():
            self._handle_save_result(self._view_model.set_custom_color(color.name()))
            self._handle_save_result(self._view_model.set_theme("custom"))

    def _mark_external_test_unconfigured(self) -> None:
        self.external_model_status_label.setText(_("External model testing is not configured."))

    def _set_bool(self, key: str, enabled: bool) -> None:
        if self._updating:
            return
        self._handle_save_result(self._view_model.set_bool(key, enabled))

    def _set_number(self, key: str, value: float) -> None:
        if self._updating:
            return
        self._handle_save_result(self._view_model.set_number(key, float(value)))

    def _set_text(self, key: str, value: str) -> None:
        if self._updating:
            return
        self._handle_save_result(self._view_model.set_text(key, value))

    def _handle_save_result(self, result: object) -> None:
        if not getattr(result, "ok", False):
            self._set_error(getattr(result, "error", None))
            return
        self.status_label.setText(_("Saved"))

    def _set_error(self, error: AppError | None) -> None:
        self._last_error = error
        self.status_label.setText(display_error_message(error))


def _card_with_form(title: str) -> CardFrame:
    card = CardFrame(object_name="settings_content_frame")
    card.content_layout.addWidget(_section_title(title))
    form = QFormLayout()
    form.setContentsMargins(0, 0, 0, 0)
    form.setSpacing(12)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
    card.content_layout.addLayout(form)
    card.form_layout = form
    return card


def _action_card(title: str, description: str) -> CardFrame:
    card = CardFrame(object_name="settings_content_frame")
    card.content_layout.addWidget(_section_title(title))
    card.content_layout.addWidget(_secondary_label(description))
    return card


def _add_action_buttons(card: CardFrame, *buttons: QPushButton) -> None:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(12)
    for button in buttons:
        row.addWidget(button)
    card.content_layout.addLayout(row)


def _section_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("settings_section_title_label")
    return label


def _secondary_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("settings_secondary_label")
    label.setProperty("role", "secondary")
    label.setWordWrap(True)
    return label


def _switch_line(label: str, switch: SwitchButton) -> QWidget:
    row = QWidget()
    row.setObjectName("settings_switch_row_widget")
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(QLabel(label))
    layout.addStretch(1)
    layout.addWidget(switch)
    return row


def _switch_row(switch: SwitchButton) -> QWidget:
    row = QWidget()
    row.setObjectName("settings_switch_row_widget")
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
    spin.setFixedWidth(220)
    return spin


def _readonly_line_edit(object_name: str) -> QLineEdit:
    line_edit = QLineEdit()
    line_edit.setObjectName(object_name)
    line_edit.setReadOnly(True)
    return line_edit


def _text_line_edit(object_name: str) -> QLineEdit:
    line_edit = QLineEdit()
    line_edit.setObjectName(object_name)
    return line_edit


def _connect_text(line_edit: QLineEdit, callback: object) -> None:
    line_edit.editingFinished.connect(callback)


def _language_label(language: str) -> str:
    labels = {
        "en_US": _("English"),
        "ja_JP": _("Japanese"),
        "ko_KR": _("Korean"),
        "zh_CN": _("Simplified Chinese"),
        "zh_TW": _("Traditional Chinese"),
    }
    return labels.get(language, language)


def _residency_setting_key() -> str | None:
    if sys.platform.startswith("win"):
        return ENABLE_TRAY_SETTING_KEY
    if sys.platform == "darwin":
        return ENABLE_MENU_BAR_SETTING_KEY
    return None
