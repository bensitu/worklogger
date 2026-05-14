"""Settings workflow controller."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from worklogger.__about__ import APP_VERSION
from worklogger.app.queries.update_queries import CheckForUpdatesQuery
from worklogger.app.use_cases.updates import CheckForUpdatesHandler, UpdateCheckResult
from worklogger.domain.auth.models import User
from worklogger.domain.shared.errors import AppError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import _
from worklogger.presentation.auth.dialogs import ChangePasswordDialog, ChangePasswordDraft
from worklogger.presentation.auth.controller import (
    ChangePasswordDialogFactory,
    RememberSessionStore,
)
from worklogger.presentation.settings.dialog import SettingsDialog
from worklogger.presentation.user_management import UserManagementDialog
from worklogger.presentation.viewmodels import (
    AuthViewModel,
    DataManagementActionState,
    DataManagementViewModel,
    SettingsViewModel,
    UserManagementViewModel,
)


SettingsDialogFactory = Callable[[SettingsViewModel, QWidget | None], SettingsDialog]
UserManagementDialogFactory = Callable[
    [UserManagementViewModel, QWidget | None],
    UserManagementDialog,
]
PathProvider = Callable[[QWidget | None], Path | None]
ConfirmationProvider = Callable[[QWidget | None], bool]
IcsImportModeProvider = Callable[[QWidget | None], bool | None]
NotificationHandler = Callable[[QWidget | None, str, str], None]
ReloadHandler = Callable[[], bool | None]


class SettingsWorkflow(Protocol):
    def open(self, parent: QWidget | None = None) -> SettingsDialog:
        ...


class LocalModelsWorkflow(Protocol):
    def open(self, parent: QWidget | None = None) -> object:
        ...


class IdentityWorkflow(Protocol):
    def open(self, parent: QWidget | None = None) -> object:
        ...


class SettingsWorkflowController:
    def __init__(
        self,
        *,
        settings_view_model: SettingsViewModel,
        auth_view_model: AuthViewModel,
        user: User,
        data_management_view_model: DataManagementViewModel,
        update_check_handler: CheckForUpdatesHandler | None = None,
        identity_workflow: IdentityWorkflow | None = None,
        local_models_workflow: LocalModelsWorkflow | None = None,
        user_management_view_model: UserManagementViewModel | None = None,
        remember_session_store: RememberSessionStore | None = None,
        dialog_factory: SettingsDialogFactory | None = None,
        change_password_dialog_factory: ChangePasswordDialogFactory | None = None,
        user_management_dialog_factory: UserManagementDialogFactory | None = None,
        backup_destination_provider: PathProvider | None = None,
        restore_source_provider: PathProvider | None = None,
        csv_destination_provider: PathProvider | None = None,
        csv_source_provider: PathProvider | None = None,
        ics_source_provider: PathProvider | None = None,
        ics_destination_provider: PathProvider | None = None,
        ics_import_mode_provider: IcsImportModeProvider | None = None,
        restore_confirmation: ConfirmationProvider | None = None,
        notify_success: NotificationHandler | None = None,
        notify_error: NotificationHandler | None = None,
        reload_after_restore: ReloadHandler | None = None,
    ) -> None:
        self._settings_view_model = settings_view_model
        self._auth_view_model = auth_view_model
        self._user = user
        self._data_management_view_model = data_management_view_model
        self._update_check_handler = update_check_handler
        self._identity_workflow = identity_workflow
        self._local_models_workflow = local_models_workflow
        self._user_management_view_model = user_management_view_model
        self._remember_session_store = remember_session_store
        self._dialog_factory = dialog_factory or SettingsDialog
        self._change_password_dialog_factory = (
            change_password_dialog_factory or ChangePasswordDialog
        )
        self._user_management_dialog_factory = (
            user_management_dialog_factory or UserManagementDialog
        )
        self._backup_destination_provider = (
            backup_destination_provider or _backup_destination
        )
        self._restore_source_provider = restore_source_provider or _restore_source
        self._csv_destination_provider = csv_destination_provider or _csv_destination
        self._csv_source_provider = csv_source_provider or _csv_source
        self._ics_source_provider = ics_source_provider or _ics_source
        self._ics_destination_provider = ics_destination_provider or _ics_destination
        self._ics_import_mode_provider = (
            ics_import_mode_provider or _choose_ics_import_mode
        )
        self._restore_confirmation = restore_confirmation or _confirm_restore
        self._notify_success = notify_success or _notify_success
        self._notify_error = notify_error or _notify_error
        self._reload_after_restore = reload_after_restore

    def create_dialog(self, parent: QWidget | None = None) -> SettingsDialog:
        dialog = self._dialog_factory(self._settings_view_model, parent)
        dialog.change_password_requested.connect(
            lambda: self._change_password(dialog)
        )
        if self._user_management_view_model is not None:
            dialog.manage_users_requested.connect(lambda: self._manage_users(dialog))
        if self._identity_workflow is not None:
            dialog.manage_identities_requested.connect(
                lambda: self._identity_workflow.open(dialog)
            )
        dialog.backup_requested.connect(lambda: self._backup_database(dialog))
        dialog.restore_requested.connect(lambda: self._restore_database(dialog))
        dialog.export_csv_requested.connect(lambda: self._export_csv(dialog))
        dialog.import_csv_requested.connect(lambda: self._import_csv(dialog))
        dialog.import_ics_requested.connect(lambda: self._import_ics(dialog))
        dialog.export_ics_requested.connect(lambda: self._export_ics(dialog))
        dialog.update_check_requested.connect(lambda: self._check_updates(dialog))
        if self._local_models_workflow is not None:
            dialog.manage_local_models_requested.connect(
                lambda: self._local_models_workflow.open(dialog)
            )
        dialog.refresh()
        return dialog

    def open(self, parent: QWidget | None = None) -> SettingsDialog:
        dialog = self.create_dialog(parent)
        dialog.exec()
        return dialog

    def _change_password(self, parent: QWidget | None) -> bool:
        dialog = self._change_password_dialog_factory(parent)
        changed = False

        def submit(draft: ChangePasswordDraft) -> None:
            nonlocal changed
            dialog.set_busy(True)
            result = self._auth_view_model.change_password(
                user_id=self._user.id,
                current_password=draft.current_password,
                new_password=draft.new_password,
                password_confirm=draft.password_confirm,
            )
            dialog.set_busy(False)
            if not result.ok or result.value is None:
                dialog.set_error(_error_message(result.error))
                return
            if self._remember_session_store is not None:
                self._remember_session_store.clear_token()
            changed = True
            dialog.set_error(_("Save this recovery key before continuing."))
            dialog.mark_complete(result.value)

        def finish() -> None:
            dialog.accept()

        dialog.change_submitted.connect(submit)
        dialog.continue_requested.connect(finish)
        dialog.exec()
        if changed:
            self._notify_success(
                parent,
                _("Change password"),
                _("Password changed successfully."),
            )
        return changed

    def _manage_users(self, parent: QWidget | None) -> UserManagementDialog:
        assert self._user_management_view_model is not None
        dialog = self._user_management_dialog_factory(
            self._user_management_view_model,
            parent,
        )
        dialog.refresh()
        dialog.exec()
        return dialog

    def _backup_database(self, dialog: SettingsDialog) -> bool:
        path = self._backup_destination_provider(dialog)
        if path is None:
            _set_status(dialog, _("Backup cancelled"))
            return False
        return self._handle_data_result(
            dialog,
            _("Backup Data"),
            self._data_management_view_model.backup_database(path),
            lambda state: _("Backup saved: {path}").format(path=state.path),
        )

    def _restore_database(self, dialog: SettingsDialog) -> bool:
        path = self._restore_source_provider(dialog)
        if path is None:
            _set_status(dialog, _("Restore cancelled"))
            return False
        validation = self._data_management_view_model.validate_restore_database(path)
        if not validation.ok:
            return self._handle_data_result(
                dialog,
                _("Restore Data"),
                validation,
                lambda _state: _("Restore validation passed."),
            )
        if not self._restore_confirmation(dialog):
            _set_status(dialog, _("Restore cancelled"))
            return False
        restored = self._handle_data_result(
            dialog,
            _("Restore Data"),
            self._data_management_view_model.restore_database(path),
            lambda _state: _("Data restored successfully."),
        )
        if restored and self._reload_after_restore is not None:
            self._reload_after_restore()
        return restored

    def _export_csv(self, dialog: SettingsDialog) -> bool:
        path = self._csv_destination_provider(dialog)
        if path is None:
            _set_status(dialog, _("Export cancelled"))
            return False
        return self._handle_data_result(
            dialog,
            _("Export CSV"),
            self._data_management_view_model.export_csv(path),
            lambda state: _("Exported {count} records.").format(
                count=state.record_count
            ),
        )

    def _import_csv(self, dialog: SettingsDialog) -> bool:
        path = self._csv_source_provider(dialog)
        if path is None:
            _set_status(dialog, _("Import cancelled"))
            return False
        return self._handle_data_result(
            dialog,
            _("Import CSV"),
            self._data_management_view_model.import_csv(path),
            lambda state: _("Imported {count} records.").format(
                count=state.record_count
            ),
        )

    def _export_ics(self, dialog: SettingsDialog) -> bool:
        path = self._ics_destination_provider(dialog)
        if path is None:
            _set_status(dialog, _("Export cancelled"))
            return False
        return self._handle_data_result(
            dialog,
            _("Export .ics"),
            self._data_management_view_model.export_ics(path),
            lambda state: _("Exported {count} events.").format(
                count=state.record_count
            ),
        )

    def _import_ics(self, dialog: SettingsDialog) -> bool:
        path = self._ics_source_provider(dialog)
        if path is None:
            _set_status(dialog, _("Import cancelled"))
            return False
        count = self._data_management_view_model.calendar_event_count()
        if not count.ok or count.value is None:
            return self._handle_data_result(
                dialog,
                _("Import .ics"),
                Result.failure(count.error or AppError("ics_import_failed", "ics_import_failed")),
                lambda _state: _("No events found."),
            )
        replace_existing = False
        if count.value > 0:
            choice = self._ics_import_mode_provider(dialog)
            if choice is None:
                _set_status(dialog, _("Import cancelled"))
                return False
            replace_existing = bool(choice)
        return self._handle_data_result(
            dialog,
            _("Import .ics"),
            self._data_management_view_model.import_ics(
                path,
                replace_existing=replace_existing,
            ),
            lambda state: (
                _("No events found.")
                if state.record_count == 0
                else _("Imported {count} calendar events.").format(
                    count=state.record_count
                )
            ),
        )

    def _check_updates(self, dialog: SettingsDialog) -> bool:
        if self._update_check_handler is None:
            _set_status(dialog, _("Update check is not configured."))
            return False
        result = self._update_check_handler.handle(CheckForUpdatesQuery(APP_VERSION))
        if not result.ok or result.value is None:
            message = _error_message(result.error)
            _set_status(dialog, message)
            self._notify_error(dialog, _("Check for updates"), message)
            return False
        message = _update_message(result.value)
        _set_status(dialog, message)
        self._notify_success(dialog, _("Check for updates"), message)
        return True

    def _handle_data_result(
        self,
        dialog: SettingsDialog,
        title: str,
        result: Result[DataManagementActionState],
        success_message: Callable[[DataManagementActionState], str],
    ) -> bool:
        if not result.ok or result.value is None:
            message = _error_message(result.error)
            _set_status(dialog, message)
            self._notify_error(dialog, title, message)
            return False
        message = success_message(result.value)
        _set_status(dialog, message)
        self._notify_success(dialog, title, message)
        return True


def _set_status(dialog: SettingsDialog, message: str) -> None:
    dialog.status_label.setText(message)


def _error_message(error: AppError | None) -> str:
    return error.message if error is not None else _("Unknown error")


def _update_message(result: UpdateCheckResult) -> str:
    if result.update_available and result.latest_version:
        return _("Update available: {version}").format(version=result.latest_version)
    return _("You are using the latest version.")


def _backup_destination(parent: QWidget | None) -> Path | None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return _save_path(
        parent,
        _("Backup Data"),
        f"worklog_backup_{stamp}.db",
        _("SQLite Database (*.db)"),
    )


def _restore_source(parent: QWidget | None) -> Path | None:
    path, _selected_filter = QFileDialog.getOpenFileName(
        parent,
        _("Restore Data"),
        "",
        _("SQLite Database (*.db)"),
    )
    return Path(path) if path else None


def _csv_destination(parent: QWidget | None) -> Path | None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return _save_path(
        parent,
        _("Export CSV"),
        f"worklog_{stamp}.csv",
        _("CSV (*.csv)"),
    )


def _csv_source(parent: QWidget | None) -> Path | None:
    path, _selected_filter = QFileDialog.getOpenFileName(
        parent,
        _("Import CSV"),
        "",
        _("CSV (*.csv)"),
    )
    return Path(path) if path else None


def _ics_destination(parent: QWidget | None) -> Path | None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return _save_path(
        parent,
        _("Export .ics"),
        f"worklog_{stamp}.ics",
        _("iCalendar (*.ics)"),
    )


def _ics_source(parent: QWidget | None) -> Path | None:
    path, _selected_filter = QFileDialog.getOpenFileName(
        parent,
        _("Import .ics"),
        "",
        _("iCalendar (*.ics)"),
    )
    return Path(path) if path else None


def _save_path(
    parent: QWidget | None,
    title: str,
    default_name: str,
    file_filter: str,
) -> Path | None:
    path, _selected_filter = QFileDialog.getSaveFileName(
        parent,
        title,
        default_name,
        file_filter,
    )
    return Path(path) if path else None


def _confirm_restore(parent: QWidget | None) -> bool:
    answer = QMessageBox.warning(
        parent,
        _("Restore Data"),
        _("Restore will replace the current database file. Continue?"),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return answer == QMessageBox.StandardButton.Yes


def _choose_ics_import_mode(parent: QWidget | None) -> bool | None:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(_("Import .ics"))
    box.setText(
        _(
            "Calendar data already exists.\n\n"
            "Replace clears previous calendar events before import.\n"
            "Append keeps existing events and adds imported events."
        )
    )
    replace_button = box.addButton(_("Replace"), QMessageBox.ButtonRole.DestructiveRole)
    append_button = box.addButton(_("Append"), QMessageBox.ButtonRole.AcceptRole)
    cancel_button = box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(append_button)
    box.exec()
    clicked = box.clickedButton()
    if clicked == cancel_button or clicked is None:
        return None
    return clicked == replace_button


def _notify_success(parent: QWidget | None, title: str, message: str) -> None:
    QMessageBox.information(parent, title, message)


def _notify_error(parent: QWidget | None, title: str, message: str) -> None:
    QMessageBox.critical(parent, title, message)
