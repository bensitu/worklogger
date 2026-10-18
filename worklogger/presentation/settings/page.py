"""Native in-shell settings page."""

from __future__ import annotations


from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QFileDialog,
    QDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from worklogger.config.constants import (
    DARK_MODE_SETTING_KEY,
    MINIMAL_MODE_SETTING_KEY,
)
from worklogger.config.themes import get_theme
from worklogger.domain.auth.models import User
from worklogger.domain.shared.errors import AppError
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
from worklogger.presentation.widgets.avatar import AvatarCropDialog
from worklogger.infrastructure.images.avatar import load_avatar_image


from worklogger.presentation.settings.sections.state import SettingsSectionState


class SettingsPage(QWidget, SettingsSectionState):
    settings_changed = Signal(object)
    backup_requested = Signal()
    open_data_directory_requested = Signal()
    change_password_requested = Signal()
    export_csv_requested = Signal()
    export_ics_requested = Signal()
    import_csv_requested = Signal()
    import_ics_requested = Signal()
    manage_identities_requested = Signal()
    manage_local_models_requested = Signal()
    manage_users_requested = Signal()
    manage_entry_types_requested = Signal()
    manage_work_modes_requested = Signal()
    entry_types_changed = Signal()
    manage_projects_requested = Signal()
    projects_changed = Signal()
    ai_availability_changed = Signal()
    logout_requested = Signal()
    restore_requested = Signal()
    update_check_requested = Signal()
    test_external_model_requested = Signal()
    profile_save_requested = Signal(str, str)
    profile_refresh_requested = Signal()
    profile_changed = Signal(object)

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
        self._account_is_admin = False
        self._manage_users_available = True
        self._update_checks_available = True
        self._model_management_available = True
        self._updating = False
        self._last_error: AppError | None = None
        self._busy_jobs: set[str] = set()
        self._residency_key = _residency_setting_key()
        self._category_pages: dict[str, int] = {}
        self._custom_color = "#4f8ef7"
        self._local_model_ready = False
        self._local_model_name = ""
        self._local_runtime_reason = None
        self._local_runtime_ready = False
        self._local_context_limit = None
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
    def state(self):
        return self._state

    @property
    def is_busy(self) -> bool:
        return bool(self._busy_jobs)

    def set_busy(self, job: str, busy: bool) -> None:
        if busy:
            self._busy_jobs.add(job)
        else:
            self._busy_jobs.discard(job)
        self.category_stack.setEnabled(not self._busy_jobs.difference({"external_model_test", "update"}))
        if job == "update":
            self.check_updates_button.setEnabled(self._update_checks_available and not busy)
        if job == "external_model_test":
            fields = (self.external_model_enabled_switch, self.external_api_key_line_edit,
                      self.external_base_url_line_edit, self.external_model_line_edit, self.test_external_model_button)
            if busy:
                self._external_test_controls = tuple((field, field.isEnabled()) for field in fields)
                for field in fields:
                    field.setEnabled(False)
            else:
                for field, enabled in getattr(self, "_external_test_controls", ()):
                    field.setEnabled(enabled)
            if not busy:
                self._update_configuration_status()

    def refresh(self) -> bool:
        result = self._view_model.load()
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return False
        self.set_state(result.value)
        self.status_label.clear()
        self.status_label.hide()
        self.profile_refresh_requested.emit()
        return True

    def set_account(self, user: User) -> None:
        self._account_is_admin = user.is_admin
        self.display_name_editor.set_profile(user)
        self.current_user_id_line_edit.setText(user.username)
        self.current_user_id_line_edit.setAccessibleName(_("Login ID"))
        self.current_user_role_line_edit.setText(
            _("Admin") if user.is_admin else _("User")
        )
        self._update_user_management_access()
        self.backup_button.setEnabled(user.is_admin)
        self.restore_button.setEnabled(user.is_admin)

    def set_profile_available(self, available: bool):
        self.display_name_editor.set_available(available)

    def set_profile_error(self, error):
        self._last_error = error
        self.display_name_editor.set_error(display_error_message(error))

    def complete_profile_save(self, user):
        self._last_error = None
        self.display_name_editor.complete_save(user)

    def confirm_profile_leave(self):
        if self.is_busy:
            return False
        if not self.display_name_editor.has_unsaved_changes:
            return True
        if QMessageBox.question(self, _("Discard changes?"), _("Discard unsaved display name changes?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return False
        self.display_name_editor.cancel_editing()
        return True

    def set_manage_users_available(self, available: bool) -> None:
        self._manage_users_available = bool(available)
        self._update_user_management_access()

    def _update_user_management_access(self) -> None:
        allowed = self._account_is_admin and self._manage_users_available
        self.account_administration_frame.setVisible(allowed)
        self.manage_users_button.setVisible(allowed)
        self.manage_users_button.setEnabled(allowed)

    def set_entry_types_available(self, available: bool) -> None:
        self.manage_entry_types_button.setEnabled(available)

    def set_work_modes_available(self, available: bool) -> None:
        self.manage_work_modes_button.setEnabled(available)

    def set_projects_available(self, available: bool) -> None:
        self.manage_projects_button.setEnabled(available)

    def set_identity_management_available(self, available: bool) -> None:
        self.manage_identities_button.setEnabled(available)
        self.manage_identities_button.setToolTip("" if available else _("Identity management is not configured."))

    def set_update_check_available(self, available: bool) -> None:
        self._update_checks_available = available
        self.check_updates_button.setEnabled(available and "update" not in self._busy_jobs)
        self.check_updates_button.setToolTip("" if available else _("Update check is not configured."))

    def set_model_management_available(self, available: bool) -> None:
        self._model_management_available = available
        self._apply_capabilities()

    def set_profile_busy(self, busy: bool) -> None:
        self.set_busy("user_profile", busy)
        self.display_name_editor.set_busy(busy)

    def set_local_model_error(self, error: AppError | None) -> None:
        self.local_model_status_label.setText(display_error_message(error))

    def set_external_test_status(self, message: str) -> None:
        self.external_model_status_label.setText(message)

    def bind_external_test_progress(self, task) -> None:
        task.started.connect(lambda: self.external_processing_progress.start(_("Testing connection...")))
        task.finished.connect(self.external_processing_progress.finish)
        self.external_processing_progress.cancel_requested.connect(task.cancel)





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

    def set_data_directory(self, directory):
        self.data_directory_input.setText(str(directory) if directory else "")
        self.open_data_directory_button.setEnabled(directory is not None)

    def _add_category(self, key: str, widget: QWidget) -> None:
        self._category_pages[key] = self.category_stack.addWidget(widget)

    def _set_category(self, key: str) -> None:
        index = self._category_pages.get(key)
        if index is not None:
            self.category_stack.setCurrentIndex(index)

    def _section_actions(self) -> SectionActions:
        return SectionActions(
            change_avatar_requested=self._change_avatar,
            reset_avatar_requested=lambda: self._handle_save_result(self._view_model.set_avatar("")),
            backup_requested=self.backup_requested.emit,
            open_data_directory_requested=self.open_data_directory_requested.emit,
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
            manage_entry_types_requested=self.manage_entry_types_requested.emit,
            manage_work_modes_requested=self.manage_work_modes_requested.emit,
            manage_projects_requested=self.manage_projects_requested.emit,
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
        section = GeneralSection(self._section_actions(), holiday_regions=self._view_model.holiday_regions,
                                 system_country=self._view_model.system_holiday_country)
        for name in section.control_names:
            setattr(self, name, getattr(section, name))
        self._populate_holiday_subdivisions(self._view_model.system_holiday_country)
        return section

    def _build_ai_page(self) -> QWidget:
        section = AISection(self._section_actions())
        for name in section.control_names:
            setattr(self, name, getattr(section, name))
        self.test_external_model_button.clicked.connect(self.test_external_model_requested.emit)
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
        self.display_name_editor.save_requested.connect(self.profile_save_requested.emit)
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

    def _change_avatar(self):
        path, _filter = QFileDialog.getOpenFileName(self, _("Change avatar"), "", _("Images (*.png *.jpg *.jpeg *.webp *.bmp)"))
        if not path:
            return
        result = load_avatar_image(path)
        if not result.ok:
            self._set_error(result.error)
            return
        dialog = AvatarCropDialog(result.value, self)
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._handle_save_result(self._view_model.set_avatar(dialog.canvas.encoded_avatar()))
        finally:
            dialog.deleteLater()

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
        self._update_custom_color_control()
        if self._updating:
            return
        result = self._view_model.set_theme(
            str(self.theme_combo.currentData() or "blue")
        )
        self._handle_save_result(result)

    def _update_custom_color_control(self) -> None:
        self.custom_color_button.setVisible(get_theme(self.theme_combo.currentData()).customizable)

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
                definition = get_theme(self.theme_combo.currentData())
                self._handle_save_result(self._view_model.set_theme(definition.key if definition.customizable else "custom"))

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











    def _set_bool(self, key: str, enabled: bool) -> None:
        if self._updating:
            return
        if key == MINIMAL_MODE_SETTING_KEY and not self._capabilities.minimal_view:
            return
        self._handle_save_result(self._view_model.set_bool(key, enabled))
        if key == MINIMAL_MODE_SETTING_KEY and self._last_error is None:
            self.set_operation_status(_("Saved. View changes apply after restarting or signing in again."))

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
        loaded = self._view_model.load(refresh_credentials=False)
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
