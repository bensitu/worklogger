"""Native in-shell settings page."""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from worklogger.config.constants import (
    DARK_MODE_SETTING_KEY,
    ENABLE_TRAY_SETTING_KEY,
    HOLIDAY_REGION_SETTING_KEY,
)
from worklogger.domain.auth.models import User
from worklogger.domain.shared.errors import AppError
from worklogger.infrastructure.calendar.holidays_provider import (
    detect_country,
    supported_holiday_regions,
)
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.settings.sections.about import AboutSection
from worklogger.presentation.settings.sections.account import AccountSection
from worklogger.presentation.settings.sections.actions import SectionActions
from worklogger.presentation.settings.sections.ai import AISection
from worklogger.presentation.settings.sections.appearance import AppearanceSection
from worklogger.presentation.settings.sections.common import (
    _residency_setting_key,
)
from worklogger.presentation.settings.sections.data import DataSection
from worklogger.presentation.settings.sections.general import GeneralSection
from worklogger.presentation.settings.sections.network import NetworkSection
from worklogger.presentation.settings_capabilities import SettingsCapabilities
from worklogger.presentation.theme import (
    configure_application_style,
    install_bundled_fonts,
)
from worklogger.presentation.viewmodels import SettingsState, SettingsViewModel
from worklogger.presentation.widgets import SettingsNav
from worklogger.presentation.widgets.color_dialog import choose_custom_color
from worklogger.presentation.widgets.icons import ui_icon


class SettingsPage(QWidget):
    settings_changed = Signal(object)
    backup_requested = Signal()
    change_password_requested = Signal()
    export_csv_requested = Signal()
    export_ics_requested = Signal()
    import_csv_requested = Signal()
    import_ics_requested = Signal()
    manage_identities_requested = Signal()
    manage_local_models_requested = Signal()
    manage_users_requested = Signal()
    manage_work_types_requested = Signal()
    work_types_changed = Signal()
    logout_requested = Signal()
    restore_requested = Signal()
    update_check_requested = Signal()

    def __init__(
        self,
        view_model: SettingsViewModel,
        parent: QWidget | None = None,
        *,
        capabilities: SettingsCapabilities | None = None,
    ) -> None:
        super().__init__(parent)
        self._view_model = view_model
        self._capabilities = capabilities or SettingsCapabilities()
        self._state: SettingsState | None = None
        self._updating = False
        self._last_error: AppError | None = None
        self._busy_jobs: set[str] = set()
        self._residency_key = _residency_setting_key()
        self._category_pages: dict[str, int] = {}
        self._custom_color = "#4f8ef7"
        self._local_model_ready = False
        self._local_model_name = ""
        self.setObjectName("settings_page_widget")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        configure_application_style()
        install_bundled_fonts()
        self._build_ui()
        self._apply_capabilities()

    @property
    def last_error(self) -> AppError | None:
        return self._last_error

    @property
    def is_busy(self) -> bool:
        return bool(self._busy_jobs)

    def set_busy(self, job: str, busy: bool) -> None:
        if busy:
            self._busy_jobs.add(job)
        else:
            self._busy_jobs.discard(job)
        self.category_stack.setEnabled(not self.is_busy)

    def refresh(self) -> bool:
        result = self._view_model.load()
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return False
        self.set_state(result.value)
        self.status_label.clear()
        self.status_label.hide()
        return True

    def set_account(self, user: User) -> None:
        self.current_user_name_line_edit.setText(user.username)
        self.current_user_id_line_edit.setText(user.username)
        self.current_user_role_line_edit.setText(
            _("Admin") if user.is_admin else _("User")
        )
        self.set_manage_users_available(user.is_admin)
        self.backup_button.setEnabled(user.is_admin)
        self.restore_button.setEnabled(user.is_admin)

    def set_manage_users_available(self, available: bool) -> None:
        self.manage_users_button.setVisible(bool(available))
        self.manage_users_button.setEnabled(bool(available))

    def set_work_types_available(self, available: bool) -> None:
        self.manage_work_types_button.setEnabled(available)

    def set_state(self, state: SettingsState) -> None:
        self._state = state
        self._updating = True
        try:
            language_index = self.language_combo.findData(state.language)
            self.language_combo.setCurrentIndex(
                language_index if language_index >= 0 else 0
            )
            theme_index = self.theme_combo.findData(state.theme)
            self.theme_combo.setCurrentIndex(theme_index if theme_index >= 0 else 0)
            self.custom_color_button.setVisible(
                self.theme_combo.currentData() == "custom"
            )
            self._custom_color = state.custom_color
            self._update_color_swatch()
            mode_index = self.mode_combo.findData(
                "dark" if state.dark_mode else "light"
            )
            self.mode_combo.setCurrentIndex(mode_index if mode_index >= 0 else 0)
            self.dark_switch.set_checked(state.dark_mode)
            self.minimal_switch.set_checked(state.minimal_mode)
            self.ai_enabled_switch.set_checked(
                state.ai_assist_enabled
                and (
                    self._capabilities.external_generation
                    or self._capabilities.local_generation
                )
            )
            self.ai_notes_switch.set_checked(state.ai_privacy_include_notes)
            self.ai_calendar_switch.set_checked(state.ai_privacy_include_calendar)
            self.ai_quick_logs_switch.set_checked(state.ai_privacy_include_quick_logs)
            self.external_base_url_line_edit.setText(state.external_model_base_url)
            self.external_model_line_edit.setText(state.external_model_name)
            self.external_api_key_line_edit.setText(state.external_api_key)
            self.external_api_key_line_edit.setEnabled(state.external_api_key_available)
            self.external_api_key_line_edit.setToolTip(
                _("Stored securely; no request is sent when saving.")
                if state.external_api_key_available
                else _("Secure credential storage is unavailable.")
            )
            self.local_model_enabled_switch.set_checked(state.local_model_enabled)
            self._update_local_model_status()
            self.standard_hours_input.setValue(state.standard_work_hours)
            self.default_break_input.setValue(state.default_break_hours)
            self.monthly_target_input.setValue(state.monthly_target_hours)
            self.holidays_switch.set_checked(state.show_holidays)
            country, _separator, subdivision = state.holiday_region.partition("/")
            index = self.holiday_country_combo.findData(country)
            self.holiday_country_combo.setCurrentIndex(max(index, 0))
            self._populate_holiday_subdivisions(
                country or detect_country(), subdivision
            )
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
            self.proxy_password_line_edit.setEnabled(
                state.proxy_password_available and state.network_proxy_enabled
            )
            self.proxy_password_visibility_action.setEnabled(
                state.proxy_password_available and state.network_proxy_enabled
            )
            self.proxy_credentials_status_label.setText(
                _("Password is stored in the system credential store.")
                if state.proxy_password_available
                else _(
                    "Secure credential storage is unavailable. Existing passwords are retained; new passwords cannot be saved."
                )
            )
            self.proxy_domain_line_edit.setText(state.network_proxy_domain)
            self._update_configuration_status()
            self.set_backup_time(state.last_backup_at)
        finally:
            self._updating = False

    def set_capabilities(self, capabilities: SettingsCapabilities) -> None:
        self._capabilities = capabilities
        self._apply_capabilities()
        if self._state is not None:
            self.set_state(self._state)

    def _apply_capabilities(self) -> None:
        available = (
            self._capabilities.external_generation
            or self._capabilities.local_generation
        )
        for widget in (
            self.ai_enabled_switch,
            self.ai_notes_switch,
            self.ai_calendar_switch,
            self.ai_quick_logs_switch,
        ):
            widget.setEnabled(available)
            widget.setToolTip(
                ""
                if available
                else _(
                    "Text processing is unavailable. Saved preferences are retained."
                )
            )
        for widget in (self.external_base_url_line_edit, self.external_model_line_edit):
            widget.setEnabled(True)
        self.external_runtime_status_label.setText(
            _("External text processing is available.")
            if self._capabilities.external_generation
            else _(
                "External text processing is unavailable. Saved preferences are retained."
            )
        )
        self.local_model_enabled_switch.setEnabled(True)
        for widget in (self.manage_local_models_button,):
            widget.setEnabled(self._capabilities.model_management)
            widget.setToolTip(
                ""
                if self._capabilities.model_management
                else _("Model file management is unavailable.")
            )
        self.proxy_enabled_switch.setEnabled(True)
        self._update_configuration_status()
        for switch, name in (
            (self.ai_enabled_switch, _("AI Assist")),
            (self.ai_notes_switch, _("Include work content")),
            (self.ai_calendar_switch, _("Include calendar")),
            (self.ai_quick_logs_switch, _("Include quick logs")),
            (self.local_model_enabled_switch, _("Enable local model")),
            (self.proxy_enabled_switch, _("Use a web proxy for this application.")),
            (self.dark_switch, _("Dark mode")),
            (self.holidays_switch, _("Public holidays")),
            (self.overnight_switch, _("Overnight indicator")),
            (self.week_start_switch, _("Start week on Monday")),
        ):
            switch.setAccessibleName(name)
        if self.residency_switch is not None:
            self.residency_switch.setAccessibleName(
                _("Enable tray icon")
                if self._residency_key == ENABLE_TRAY_SETTING_KEY
                else _("Enable menu bar")
            )

    def _update_configuration_status(self) -> None:
        state = self._state
        for widget in (
            self.proxy_address_line_edit,
            self.proxy_port_line_edit,
            self.proxy_username_line_edit,
            self.proxy_domain_line_edit,
        ):
            widget.setEnabled(bool(state and state.network_proxy_enabled))
        if state is None:
            return
        self.local_runtime_status_label.setText(
            _("Local model is disabled.")
            if not state.local_model_enabled
            else _("Local text processing is available.")
            if self._capabilities.local_generation
            else _(
                "Local preference is enabled, but no inference service is connected."
            )
        )
        port = state.network_proxy_port.strip()
        configured = bool(
            state.network_proxy_address.strip()
            and len(port) <= 5
            and port.isdecimal()
            and 0 < int(port) <= 65535
        )
        self.proxy_runtime_status_label.setText(
            _("Web proxy is disabled.")
            if not state.network_proxy_enabled
            else _("Enter a proxy address and port.")
            if not configured
            else _("Proxy routing is available.")
            if self._capabilities.proxy_routing
            else _("Proxy settings are saved, but no proxy transport is connected.")
        )

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 18)
        root.setSpacing(16)

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
        self.category_nav.setFixedWidth(165)
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

        self.status_label = QLabel("")
        self.status_label.setObjectName("settings_status_label")
        self.status_label.setProperty("role", "secondary")
        root.addWidget(self.status_label)

    def _add_category(self, key: str, widget: QWidget) -> None:
        self._category_pages[key] = self.category_stack.addWidget(widget)

    def _set_category(self, key: str) -> None:
        index = self._category_pages.get(key)
        if index is not None:
            self.category_stack.setCurrentIndex(index)

    def _section_actions(self) -> SectionActions:
        return SectionActions(
            backup_requested=self.backup_requested.emit,
            change_password_requested=self.change_password_requested.emit,
            choose_custom_color=self._choose_custom_color,
            confirm_logout=self._confirm_logout,
            export_csv_requested=self.export_csv_requested.emit,
            export_ics_requested=self.export_ics_requested.emit,
            holiday_country_changed=self._holiday_country_changed,
            holiday_subdivision_changed=self._holiday_subdivision_changed,
            import_csv_requested=self.import_csv_requested.emit,
            import_ics_requested=self.import_ics_requested.emit,
            language_changed=self._language_changed,
            manage_identities_requested=self.manage_identities_requested.emit,
            manage_local_models_requested=self.manage_local_models_requested.emit,
            manage_users_requested=self.manage_users_requested.emit,
            manage_work_types_requested=self.manage_work_types_requested.emit,
            mode_changed=self._mode_changed,
            residency_key=self._residency_key,
            restore_requested=self.restore_requested.emit,
            save_external_api_key=self._save_external_api_key,
            set_bool=self._set_bool,
            set_number=self._set_number,
            set_text=self._set_text,
            theme_changed=self._theme_changed,
            toggle_proxy_password=self._toggle_proxy_password,
            update_check_requested=self.update_check_requested.emit,
        )

    def _build_appearance_page(self) -> QWidget:
        section = AppearanceSection(self._section_actions())
        for name in section.control_names:
            setattr(self, name, getattr(section, name))
        return section

    def _build_general_page(self) -> QWidget:
        section = GeneralSection(self._section_actions())
        for name in section.control_names:
            setattr(self, name, getattr(section, name))
        self._populate_holiday_subdivisions(detect_country())
        return section

    def _build_ai_page(self) -> QWidget:
        section = AISection(self._section_actions())
        for name in section.control_names:
            setattr(self, name, getattr(section, name))
        return section

    def _build_data_page(self) -> QWidget:
        section = DataSection(self._section_actions())
        for name in section.control_names:
            setattr(self, name, getattr(section, name))
        return section

    def _build_network_page(self) -> QWidget:
        section = NetworkSection(self._section_actions())
        for name in section.control_names:
            setattr(self, name, getattr(section, name))
        return section

    def _build_account_page(self) -> QWidget:
        section = AccountSection(self._section_actions())
        for name in section.control_names:
            setattr(self, name, getattr(section, name))
        return section

    def _build_about_page(self) -> QWidget:
        section = AboutSection(self._section_actions())
        for name in section.control_names:
            setattr(self, name, getattr(section, name))
        return section

    def _confirm_logout(self) -> None:
        if (
            QMessageBox.question(
                self,
                _("Log Out"),
                _("Log out of your account?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        ):
            self.logout_requested.emit()

    def _language_changed(self) -> None:
        if self._updating:
            return
        self._handle_save_result(
            self._view_model.set_language(
                str(self.language_combo.currentData() or "en_US")
            )
        )
        if self._last_error is None:
            self.status_label.setText(
                _("Saved. Language changes apply after restarting.")
            )

    def _theme_changed(self) -> None:
        self.custom_color_button.setVisible(self.theme_combo.currentData() == "custom")
        if self._updating:
            return
        result = self._view_model.set_theme(
            str(self.theme_combo.currentData() or "blue")
        )
        self._handle_save_result(result)

    def _mode_changed(self) -> None:
        if self._updating:
            return
        mode = str(self.mode_combo.currentData() or "light")
        self._set_bool(DARK_MODE_SETTING_KEY, mode == "dark")

    def _choose_custom_color(self) -> None:
        color = choose_custom_color(QColor(self._custom_color), self)
        if color.isValid():
            result = self._view_model.set_custom_color(color.name())
            self._handle_save_result(result)
            if result.ok:
                self._handle_save_result(self._view_model.set_theme("custom"))

    def _update_color_swatch(self) -> None:
        pixmap = QPixmap(20, 20)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._custom_color))
        painter.drawRoundedRect(1, 1, 18, 18, 3, 3)
        painter.end()
        self.custom_color_button.setIcon(QIcon(pixmap))

    def _toggle_proxy_password(self) -> None:
        visible = (
            self.proxy_password_line_edit.echoMode() == QLineEdit.EchoMode.Password
        )
        self.proxy_password_line_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        )
        self.proxy_password_visibility_action.setIcon(
            ui_icon("eye-off" if visible else "eye")
        )
        self.proxy_password_visibility_action.setToolTip(
            _("Hide password") if visible else _("Show password")
        )

    def _save_external_api_key(self) -> None:
        if (
            self._updating
            or self._state is None
            or self.external_api_key_line_edit.text() == self._state.external_api_key
        ):
            return
        result = self._view_model.set_external_api_key(
            self.external_api_key_line_edit.text()
        )
        self._handle_save_result(result)

    def set_local_model_status(self, *, ready: bool, name: str = "") -> None:
        self._local_model_ready = ready
        self._local_model_name = name
        self._update_local_model_status()

    def _update_local_model_status(self) -> None:
        text = (
            _("Selected model file: {name}").format(
                name=self._local_model_name or _("Local Model")
            )
            if self._local_model_ready
            else _("No verified model file selected.")
        )
        self.local_model_status_label.setText(text)

    def set_backup_time(self, value: str) -> None:
        try:
            stamp = datetime.fromisoformat(value)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            days = max(0, (datetime.now(timezone.utc) - stamp).days)
            text = _("Last backup: {time}").format(
                time=stamp.astimezone().strftime("%Y-%m-%d %H:%M")
            )
            if days >= 30:
                text += "\n" + _("No backup in {days} days. Back up your data.").format(
                    days=days
                )
        except (ValueError, TypeError):
            text = _("No backup recorded. Back up your data.")
        self.backup_status_label.setText(text)

    def set_operation_status(self, message: str, category: str | None = None) -> None:
        label = (
            self.update_status_label
            if category == "update"
            else self.data_status_label
            if category == "data"
            else self.status_label
        )
        label.setText(message)
        label.setVisible(bool(message))
        # Keep the compatibility status value without showing a duplicate footer.
        if label is not self.status_label:
            self.status_label.setText(message)
            self.status_label.hide()

    def _populate_holiday_subdivisions(
        self, country: str, subdivision: str = ""
    ) -> None:
        blocked = self.holiday_subdivision_combo.blockSignals(True)
        try:
            self.holiday_subdivision_combo.clear()
            self.holiday_subdivision_combo.addItem(_("National holidays"), "")
            for code in sorted(supported_holiday_regions().get(country, ())):
                self.holiday_subdivision_combo.addItem(code, code)
            self.holiday_subdivision_combo.setCurrentIndex(
                max(0, self.holiday_subdivision_combo.findData(subdivision))
            )
            self.holiday_subdivision_combo.setEnabled(
                self.holiday_subdivision_combo.count() > 1
            )
        finally:
            self.holiday_subdivision_combo.blockSignals(blocked)

    def _holiday_country_changed(self) -> None:
        if self._updating:
            return
        country = str(self.holiday_country_combo.currentData() or "")
        self._set_text(HOLIDAY_REGION_SETTING_KEY, country)

    def _holiday_subdivision_changed(self) -> None:
        if self._updating:
            return
        subdivision = str(self.holiday_subdivision_combo.currentData() or "")
        country = str(self.holiday_country_combo.currentData() or detect_country())
        self._set_text(
            HOLIDAY_REGION_SETTING_KEY,
            f"{country}/{subdivision}" if subdivision else country,
        )

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
        self._last_error = None
        loaded = self._view_model.load()
        if not loaded.ok or loaded.value is None:
            self._set_error(loaded.error)
            return
        self.set_state(loaded.value)
        self.settings_changed.emit(loaded.value)
        self.set_operation_status(_("Saved"))

    def _set_error(self, error: AppError | None) -> None:
        self._last_error = error
        if error is not None and error.code == "invalid_proxy_port":
            message = _("Enter a port between 0 and 65535.")
        elif error is not None and error.code == "credential_storage_unavailable":
            message = _("Secure credential storage is unavailable.")
        else:
            message = display_error_message(error)
        self.set_operation_status(message)
