"""Settings-section state binding without owning navigation or workflows."""

from datetime import datetime, timezone

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QApplication, QLineEdit

from worklogger.config.constants import (
    ENABLE_TRAY_SETTING_KEY,
    HOLIDAY_REGION_SETTING_KEY,
)
from worklogger.domain.local_model.preferences import (
    DEFAULT_RUNTIME_CONTEXT_TOKENS,
    MAX_RUNTIME_CONTEXT_TOKENS,
    MIN_RUNTIME_CONTEXT_TOKENS,
)
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_code
from worklogger.presentation.settings_capabilities import SettingsCapabilities
from worklogger.presentation.viewmodels import SettingsState
from worklogger.presentation.widgets.avatar import avatar_pixmap


class SettingsSectionState:
    def set_state(self, state: SettingsState) -> None:
        editor = QApplication.focusWidget()
        editing = (editor.text(), editor.cursorPosition(), editor.selectionStart(), editor.selectedText()) if (
            isinstance(editor, QLineEdit) and self.isAncestorOf(editor)) else None
        self._state = state
        self._updating = True
        try:
            language_index = self.language_combo.findData(state.language)
            self.language_combo.setCurrentIndex(
                max(language_index, 0)
            )
            theme_index = self.theme_combo.findData(state.theme)
            self.theme_combo.setCurrentIndex(max(theme_index, 0))
            self._update_custom_color_control()
            self._custom_color = state.custom_color
            self._update_color_swatch()
            mode_index = self.mode_combo.findData(
                "dark" if state.dark_mode else "light"
            )
            self.mode_combo.setCurrentIndex(max(mode_index, 0))
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
            self.external_model_enabled_switch.set_checked(state.external_model_enabled)
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
            self._update_local_context()
            self.standard_hours_input.setValue(state.standard_work_hours)
            self.default_break_input.setValue(state.default_break_hours)
            self.timer_reminder_input.setValue(state.timer_reminder_hours)
            self.continuous_timer_reminder_input.setValue(state.continuous_timer_reminder_hours)
            self.monthly_target_input.setValue(state.monthly_target_hours)
            self.target_mode_combo.setCurrentIndex(max(0, self.target_mode_combo.findData(state.work_target_mode)))
            self.work_schedule_editor.set_schedule(state.work_schedule)
            self.holidays_switch.set_checked(state.show_holidays)
            country, _separator, subdivision = state.holiday_region.partition("/")
            index = self.holiday_country_combo.findData(country)
            self.holiday_country_combo.setCurrentIndex(max(index, 0))
            self._populate_holiday_subdivisions(
                (country if index >= 0 else "") or self._view_model.system_holiday_country,
                subdivision if index >= 0 else ""
            )
            self.note_markers_switch.set_checked(state.show_note_markers)
            self.overnight_switch.set_checked(state.show_overnight_indicator)
            self.recent_context_switch.set_checked(state.show_recent_context)
            self.week_start_switch.set_checked(state.week_start_monday)
            if self.residency_switch is not None:
                self.residency_switch.set_checked(
                    state.enable_tray
                    if self._residency_key == ENABLE_TRAY_SETTING_KEY
                    else state.enable_menu_bar
                )
                self.close_action_combo.setCurrentIndex(self.close_action_combo.findData(state.window_close_action))
                self.minimize_to_tray_switch.set_checked(state.minimize_to_tray)
                self.category_stack.widget(self._category_pages["general"]).refresh_window_behavior()
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
            self.avatar_preview_label.setPixmap(avatar_pixmap(state.profile_avatar_png))
            self.reset_avatar_button.setEnabled(bool(state.profile_avatar_png))
        finally:
            if editing is not None:
                text, cursor, selection_start, selection = editing
                with QSignalBlocker(editor):
                    if editor.text() != text:
                        editor.setText(text)
                    editor.setCursorPosition(cursor)
                    if selection_start >= 0:
                        editor.setSelection(selection_start, len(selection))
            self._updating = False

    def set_capabilities(self, capabilities: SettingsCapabilities) -> None:
        self._capabilities = capabilities
        self._apply_capabilities()
        if self._state is not None:
            self.set_state(self._state)

    def _apply_capabilities(self) -> None:
        self.cloud_backup_panel.set_available(self._capabilities.cloud_backup_enabled)
        ai_section = self.category_stack.widget(self._category_pages["ai"])
        ai_section.content_widget.setEnabled(self._capabilities.ai_enabled)
        self.minimal_view_row.setVisible(self._capabilities.minimal_view)
        self.minimal_switch.setEnabled(self._capabilities.minimal_view)
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
        self.external_model_enabled_switch.setEnabled(self._capabilities.external_generation)
        self.external_model_enabled_switch.setAccessibleName(_("Use external model"))
        for widget in (self.manage_local_models_button,):
            widget.setEnabled(self._capabilities.model_management and self._model_management_available)
            widget.setToolTip(
                _("Local model management is not configured.")
                if not self._model_management_available
                else ""
                if self._capabilities.model_management
                else _("Model file management is unavailable.")
            )
        self.proxy_enabled_switch.setEnabled(True)
        self._update_configuration_status()
        for switch, name in (
            (self.ai_enabled_switch, _("AI Assist")),
            (self.ai_notes_switch, _("Include work content")),
            (self.ai_calendar_switch, _("Include calendar")),
            (self.ai_quick_logs_switch, _("Include previous entries")),
            (self.local_model_enabled_switch, _("Enable local model")),
            (self.proxy_enabled_switch, _("Use a web proxy for this application.")),
            (self.dark_switch, _("Dark mode")),
            (self.holidays_switch, _("Public holidays")),
            (self.overnight_switch, _("Overnight indicator")),
            (self.recent_context_switch, _("Show recent context")),
            (self.week_start_switch, _("Start week on Monday")),
        ):
            switch.setAccessibleName(name)
        if self.residency_switch is not None:
            self.residency_switch.setAccessibleName(
                _("Enable tray icon")
                if self._residency_key == ENABLE_TRAY_SETTING_KEY
                else _("Enable menu bar icon")
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
        external_ready = bool(self._capabilities.external_generation and state.external_model_enabled
                              and state.external_model_base_url and state.external_model_name and state.external_api_key)
        self.test_external_model_button.setEnabled(external_ready)
        self.test_external_model_button.setToolTip(_("Test connection using sample text; no work records are included."))
        self.external_model_status_label.setText("" if external_ready else _("Configure the address, model, and API key to test the connection."))
        if state.external_api_key_error:
            self.external_model_status_label.setText(display_error_code(state.external_api_key_error))
        if state.proxy_password_error:
            self.proxy_credentials_status_label.setText(display_error_code(state.proxy_password_error))
        self.external_runtime_status_label.setText(
            _("Text processing source: external model.") if external_ready else
            _("External processing is disabled.") if not state.external_model_enabled else
            _("External model configuration is incomplete."))
        self.local_runtime_status_label.setText(
            _("Local model is disabled.")
            if not state.local_model_enabled
            else _("Local text processing is available.")
            if self._capabilities.local_generation
            else _(
                "Local preference is enabled, but no inference service is connected."
            )
        )
        if self._local_runtime_reason is not None and state.local_model_enabled:
            self.local_runtime_status_label.setText(
                _("Local model is ready. It loads when text processing starts.") if self._local_runtime_ready
                else display_error_code(self._local_runtime_reason)
            )
        if not self._capabilities.ai_enabled:
            message = display_error_code("ai_service_disabled")
            self.external_runtime_status_label.setText(message)
            self.local_runtime_status_label.setText(message)
            self.external_model_status_label.setText(message)
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

    def set_local_model_status(self, *, ready: bool, name: str = "") -> None:
        self._local_model_ready = ready
        self._local_model_name = name
        self._update_local_model_status()

    def set_local_model_context_limit(self, limit: int | None):
        self._local_context_limit = limit
        self._update_local_context()

    def _update_local_context(self):
        if not hasattr(self, "local_context_spin_box"):
            return
        limit = self._local_context_limit
        requested = self._state.local_model_context_tokens if self._state else DEFAULT_RUNTIME_CONTEXT_TOKENS
        valid_limit = limit is not None and limit >= MIN_RUNTIME_CONTEXT_TOKENS
        maximum = min(limit, MAX_RUNTIME_CONTEXT_TOKENS) if valid_limit else MAX_RUNTIME_CONTEXT_TOKENS
        effective = min(requested, maximum)
        with QSignalBlocker(self.local_context_spin_box):
            self.local_context_spin_box.setRange(MIN_RUNTIME_CONTEXT_TOKENS, maximum)
            self.local_context_spin_box.setValue(effective)
        self.local_context_spin_box.setEnabled(valid_limit)
        self.local_context_limit_label.setText(_("{count} tokens").format(count=limit) if limit is not None else _("Unknown"))
        if valid_limit and requested > maximum:
            status = _("Saved preference: {requested} tokens; effective context: {effective} tokens.").format(
                requested=requested, effective=effective)
        elif valid_limit:
            status = _("Effective context: {count} tokens.").format(count=effective)
        elif limit is not None:
            status = display_error_code("local_model_context_limit_invalid")
        else:
            status = _("No model selected.")
        if valid_limit and effective > DEFAULT_RUNTIME_CONTEXT_TOKENS:
            status += "\n" + _("Larger context windows increase memory use and may prevent the model from loading.")
        self.local_context_status_label.setText(status)

    def set_local_runtime_status(self, *, ready: bool, reason: str):
        self._local_runtime_ready = ready
        self._local_runtime_reason = reason
        self._update_configuration_status()

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
        label.setVisible(bool(message) or category == "update")
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
            for code in sorted(self._view_model.holiday_regions.get(country, ())):
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
        country = str(self.holiday_country_combo.currentData() or self._view_model.system_holiday_country)
        self._set_text(
            HOLIDAY_REGION_SETTING_KEY,
            f"{country}/{subdivision}" if subdivision else country,
        )
