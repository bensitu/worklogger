"""Settings workflow controller."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget
from shiboken6 import isValid

from worklogger.__about__ import APP_VERSION
from worklogger.app.job_runner import JobHandle, JobRunner
from worklogger.app.queries.update_queries import CheckForUpdatesQuery
from worklogger.app.use_cases.updates import CheckForUpdatesHandler, UpdateCheckResult
from worklogger.app.use_cases.data_portability import WorkLogCsvImportPreview
from worklogger.domain.auth.models import User
from worklogger.domain.shared.errors import AppError, CancellationError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.auth.dialogs import ChangePasswordDialog, ChangePasswordDraft
from worklogger.presentation.auth.controller import (
    ChangePasswordDialogFactory,
    RememberSessionStore,
)
from worklogger.presentation.settings.dialog import SettingsDialog
from worklogger.presentation.settings.page import SettingsPage
from worklogger.presentation.user_management import UserManagementDialog
from worklogger.presentation.viewmodels import (
    AuthViewModel,
    DataManagementActionState,
    DataManagementViewModel,
    SettingsViewModel,
    UserManagementViewModel,
)


SettingsDialogFactory = Callable[[SettingsViewModel, QWidget | None], SettingsDialog]
SettingsPageFactory = Callable[[SettingsViewModel, QWidget | None], SettingsPage]
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
        job_runner: JobRunner | None = None,
        identity_workflow: IdentityWorkflow | None = None,
        local_models_workflow: LocalModelsWorkflow | None = None,
        user_management_view_model: UserManagementViewModel | None = None,
        remember_session_store: RememberSessionStore | None = None,
        dialog_factory: SettingsDialogFactory | None = None,
        page_factory: SettingsPageFactory | None = None,
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
        csv_confirmation: Callable[[QWidget, WorkLogCsvImportPreview], bool] | None = None,
        notify_success: NotificationHandler | None = None,
        notify_error: NotificationHandler | None = None,
        reload_after_restore: ReloadHandler | None = None,
    ) -> None:
        self._settings_view_model = settings_view_model
        self._auth_view_model = auth_view_model
        self._user = user
        self._data_management_view_model = data_management_view_model
        self._update_check_handler = update_check_handler
        self._job_runner = job_runner
        self._update_check_handle: JobHandle[object] | None = None
        self._data_job_handle: JobHandle[object] | None = None
        self._restore_validation_handle: JobHandle[object] | None = None
        self._identity_workflow = identity_workflow
        self._local_models_workflow = local_models_workflow
        self._user_management_view_model = user_management_view_model
        self._remember_session_store = remember_session_store
        self._dialog_factory = dialog_factory or SettingsDialog
        self._page_factory = page_factory or SettingsPage
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
        self._csv_confirmation = csv_confirmation or _confirm_csv_import
        self._notify_success = notify_success or _notify_success
        self._notify_error = notify_error or _notify_error
        self._reload_after_restore = reload_after_restore

    def create_dialog(self, parent: QWidget | None = None) -> SettingsDialog:
        dialog = self._dialog_factory(self._settings_view_model, parent)
        self._bind_surface(dialog)
        dialog.refresh()
        return dialog

    def set_restore_handler(self, handler: ReloadHandler) -> None:
        self._reload_after_restore = handler

    def create_page(self, parent: QWidget | None = None) -> SettingsPage:
        page = self._page_factory(self._settings_view_model, parent)
        self._bind_surface(page)
        page.refresh()
        return page

    def _bind_surface(self, surface: QWidget) -> None:
        if hasattr(surface, "set_account"):
            surface.set_account(self._user)
        if hasattr(surface, "set_manage_users_available"):
            surface.set_manage_users_available(
                self._user_management_view_model is not None and self._user.is_admin
            )
        surface.change_password_requested.connect(
            lambda: self._change_password(surface)
        )
        if self._user_management_view_model is not None:
            surface.manage_users_requested.connect(lambda: self._manage_users(surface))
        if self._identity_workflow is not None:
            surface.manage_identities_requested.connect(
                lambda: self._identity_workflow.open(surface)
            )
        elif hasattr(surface, "manage_identities_button"):
            surface.manage_identities_button.setEnabled(False)
            surface.manage_identities_button.setToolTip(_("Identity management is not configured."))
        surface.backup_requested.connect(lambda: self._backup_database(surface))
        surface.restore_requested.connect(lambda: self._restore_database(surface))
        surface.export_csv_requested.connect(lambda: self._export_csv(surface))
        surface.import_csv_requested.connect(lambda: self._import_csv(surface))
        surface.import_ics_requested.connect(lambda: self._import_ics(surface))
        surface.export_ics_requested.connect(lambda: self._export_ics(surface))
        surface.update_check_requested.connect(lambda: self._check_updates(surface))
        if self._update_check_handler is None and hasattr(surface, "check_updates_button"):
            surface.check_updates_button.setEnabled(False)
            surface.check_updates_button.setToolTip(_("Update check is not configured."))
        if self._local_models_workflow is not None:
            surface.manage_local_models_requested.connect(
                lambda: self._open_local_models(surface)
            )
            self._refresh_local_models_status(surface)
        elif hasattr(surface, "manage_local_models_button"):
            surface.manage_local_models_button.setEnabled(False)
            surface.manage_local_models_button.setToolTip(_("Local model management is not configured."))
        for action, signal, button in (
            ("open_for_import", "import_local_model_requested", "import_local_model_button"),
            ("open_for_download", "download_local_model_requested", "download_local_model_button"),
        ):
            handler = getattr(self._local_models_workflow, action, None)
            if handler is not None:
                getattr(surface, signal).connect(lambda handler=handler: self._open_local_model_action(surface, handler))
            else:
                getattr(surface, button).setEnabled(False)
                getattr(surface, button).setToolTip(_("Local model management is not configured."))

    def _open_local_model_action(self, surface: QWidget, handler: Callable) -> None:
        handler(surface)
        self._refresh_local_models_status(surface)

    def _open_local_models(self, surface: QWidget) -> None:
        self._local_models_workflow.open(surface)
        self._refresh_local_models_status(surface)

    def _refresh_local_models_status(self, surface: QWidget) -> None:
        view_model = getattr(self._local_models_workflow, "view_model", None)
        label = getattr(surface, "local_model_status_label", None)
        if view_model is None or label is None:
            return

        def complete(result: object) -> None:
            if not isValid(label):
                return
            if not result.ok or result.value is None:
                label.setText(_error_message(result.error))
                return
            inventory = result.value.inventory
            active = next((item for item in inventory.items if item.entry.id == inventory.active_model_id), None)
            if hasattr(surface, "set_local_model_status"):
                surface.set_local_model_status(ready=active is not None and active.verified,
                                               name=active.entry.display_name if active is not None else "")

        if self._job_runner is None:
            complete(view_model.load())
        else:
            self._job_runner.submit("local_model_status", lambda _token: view_model.load(), on_complete=complete)

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

    def _backup_database(self, dialog: QWidget) -> bool:
        path = self._backup_destination_provider(dialog)
        if path is None:
            _set_status(dialog, _("Backup cancelled"))
            return False
        return self._run_data_job(
            dialog,
            _("Backup Data"),
            lambda: self._data_management_view_model.backup_database(path),
            lambda state: _("Backup saved: {path}").format(path=state.path),
            _("Backing up data..."),
        )

    def _restore_database(self, dialog: QWidget) -> bool:
        if self._data_job_handle is not None or self._restore_validation_handle is not None:
            _set_status(dialog, _("Please wait for the current data operation."))
            return False
        path = self._restore_source_provider(dialog)
        if path is None:
            _set_status(dialog, _("Restore cancelled"))
            return False
        if self._job_runner is not None:
            _set_status(dialog, _("Validating backup..."))
            _set_busy(dialog, "data", True)
            self._restore_validation_handle = JobHandle(job_id="restore_validate_pending", cancel=lambda: None)
            handle = self._job_runner.submit(
                "restore_validate",
                lambda _token: self._data_management_view_model.validate_restore_database(path),
                on_complete=lambda result: self._restore_validated(dialog, path, result),
            )
            if self._restore_validation_handle is not None:
                self._restore_validation_handle = handle
            return True
        return self._restore_validated(dialog, path, self._data_management_view_model.validate_restore_database(path))

    def _restore_validated(self, dialog: QWidget, path: Path, validation: object) -> bool:
        self._restore_validation_handle = None
        _set_busy(dialog, "data", False)
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
        restored = self._run_data_job(
            dialog,
            _("Restore Data"),
            lambda: self._data_management_view_model.restore_database(path),
            lambda _state: _("Data restored successfully."),
            _("Restoring data..."),
        )
        if restored and self._job_runner is None and self._reload_after_restore is not None:
            self._reload_after_restore()
        return restored

    def _export_csv(self, dialog: QWidget) -> bool:
        path = self._csv_destination_provider(dialog)
        if path is None:
            _set_status(dialog, _("Export cancelled"))
            return False
        return self._run_data_job(
            dialog,
            _("Export CSV"),
            lambda: self._data_management_view_model.export_csv(path),
            lambda state: _("Exported {count} records.").format(
                count=state.record_count
            ),
            _("Exporting CSV..."),
        )

    def _import_csv(self, dialog: QWidget) -> bool:
        if self._data_job_handle is not None or self._restore_validation_handle is not None:
            _set_status(dialog, _("Please wait for the current data operation."))
            return False
        path = self._csv_source_provider(dialog)
        if path is None:
            _set_status(dialog, _("Import cancelled"))
            return False
        if self._job_runner is None:
            return self._complete_csv_preview(dialog, path, self._data_management_view_model.preview_csv(path))
        _set_busy(dialog, "data", True)
        self._data_job_handle = JobHandle(job_id="csv_preview_pending", cancel=lambda: None)
        handle = self._job_runner.submit(
            "csv_preview", lambda _token: self._data_management_view_model.preview_csv(path),
            on_complete=lambda result: self._complete_csv_preview(dialog, path, result),
        )
        if self._data_job_handle is not None:
            self._data_job_handle = handle
        return True

    def _complete_csv_preview(self, dialog: QWidget, path: Path, result: Result[WorkLogCsvImportPreview]) -> bool:
        self._data_job_handle = None
        if not isValid(dialog):
            return False
        _set_busy(dialog, "data", False)
        if not result.ok or result.value is None:
            return self._handle_data_result(dialog, _("Import CSV"), Result.failure(result.error), lambda _state: "")
        preview = result.value
        if not self._csv_confirmation(dialog, preview):
            _set_status(dialog, _("Import cancelled"))
            return False
        return self._run_data_job(
            dialog,
            _("Import CSV"),
            lambda: self._data_management_view_model.import_csv(path, preview=preview, overwrite=preview.existing_count > 0),
            lambda state: _("Imported {count} records.").format(count=state.record_count),
            _("Importing CSV..."),
        )

    def _export_ics(self, dialog: QWidget) -> bool:
        path = self._ics_destination_provider(dialog)
        if path is None:
            _set_status(dialog, _("Export cancelled"))
            return False
        return self._run_data_job(
            dialog,
            _("Export .ics"),
            lambda: self._data_management_view_model.export_ics(path),
            lambda state: _("Exported {count} events.").format(
                count=state.record_count
            ),
            _("Exporting .ics..."),
        )

    def _import_ics(self, dialog: QWidget) -> bool:
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
        return self._run_data_job(
            dialog,
            _("Import .ics"),
            lambda: self._data_management_view_model.import_ics(
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
            _("Importing .ics..."),
        )

    def _check_updates(self, dialog: QWidget) -> bool:
        if self._update_check_handler is None:
            _set_status(dialog, _("Update check is not configured."), "update")
            return False
        if self._job_runner is not None:
            if self._update_check_handle is not None:
                _set_status(dialog, _("Please wait for the current update check."), "update")
                return False
            _set_status(dialog, _("Checking for updates..."), "update")
            _set_busy(dialog, "update", True)
            if hasattr(dialog, "check_updates_button"):
                dialog.check_updates_button.setEnabled(False)
            self._update_check_handle = JobHandle(
                job_id="check_updates_pending",
                cancel=lambda: None,
            )
            handle = self._job_runner.submit(
                "check_updates",
                lambda _token: self._update_check_handler.handle(
                    CheckForUpdatesQuery(APP_VERSION)
                ),
                on_complete=lambda result: self._complete_update_check(dialog, result),
            )
            if self._update_check_handle is not None:
                self._update_check_handle = handle
            return True
        result = self._update_check_handler.handle(CheckForUpdatesQuery(APP_VERSION))
        return self._handle_update_result(dialog, result)

    def _complete_update_check(self, dialog: QWidget, result: object) -> None:
        self._update_check_handle = None
        _set_busy(dialog, "update", False)
        if hasattr(dialog, "check_updates_button"):
            dialog.check_updates_button.setEnabled(True)
        self._handle_update_result(dialog, result)

    def _handle_update_result(self, dialog: QWidget, result: object) -> bool:
        if not result.ok or result.value is None:
            message = _error_message(result.error)
            _set_status(dialog, message, "update")
            if not isinstance(result.error, CancellationError):
                self._notify_error(dialog, _("Check for updates"), message)
            return False
        message = _update_message(result.value)
        _set_status(dialog, message, "update")
        self._notify_success(dialog, _("Check for updates"), message)
        return True

    def _handle_data_result(
        self,
        dialog: QWidget,
        title: str,
        result: Result[DataManagementActionState],
        success_message: Callable[[DataManagementActionState], str],
    ) -> bool:
        if not result.ok or result.value is None:
            message = _error_message(result.error)
            _set_status(dialog, message, "data")
            if not isinstance(result.error, CancellationError):
                self._notify_error(dialog, title, message)
            return False
        message = success_message(result.value)
        if result.value.action == "backup":
            recorded = self._settings_view_model.record_backup()
            if recorded.ok:
                loaded = self._settings_view_model.load()
                if loaded.ok and loaded.value is not None and hasattr(dialog, "set_backup_time"):
                    dialog.set_backup_time(loaded.value.last_backup_at)
            else:
                message += "\n" + _("Backup succeeded, but its timestamp could not be saved.")
        _set_status(dialog, message, "data")
        self._notify_success(dialog, title, message)
        return True

    def _run_data_job(
        self,
        dialog: QWidget,
        title: str,
        job: Callable[[], Result[DataManagementActionState]],
        success_message: Callable[[DataManagementActionState], str],
        busy_message: str,
    ) -> bool:
        if self._job_runner is None:
            return self._handle_data_result(dialog, title, job(), success_message)
        if self._data_job_handle is not None or self._restore_validation_handle is not None:
            _set_status(dialog, _("Please wait for the current data operation."))
            return False
        _set_status(dialog, busy_message, "data")
        _set_busy(dialog, "data", True)
        self._data_job_handle = JobHandle(
            job_id="data_management_pending",
            cancel=lambda: None,
        )
        handle = self._job_runner.submit(
            "data_management",
            lambda _token: job(),
            on_complete=lambda result: self._complete_data_job(
                dialog,
                title,
                result,
                success_message,
            ),
        )
        if self._data_job_handle is not None:
            self._data_job_handle = handle
        return True

    def _complete_data_job(
        self,
        dialog: QWidget,
        title: str,
        result: object,
        success_message: Callable[[DataManagementActionState], str],
    ) -> None:
        self._data_job_handle = None
        _set_busy(dialog, "data", False)
        completed = self._handle_data_result(dialog, title, result, success_message)
        if (
            completed
            and result.value is not None
            and result.value.action == "restore"
            and self._reload_after_restore is not None
        ):
            self._reload_after_restore()


def _set_status(dialog: QWidget, message: str, category: str | None = None) -> None:
    if hasattr(dialog, "set_operation_status"):
        if category is None:
            category = "data"
        dialog.set_operation_status(message, category)
    else:
        dialog.status_label.setText(message)


def _set_busy(surface: QWidget, job: str, busy: bool) -> None:
    if hasattr(surface, "set_busy"):
        surface.set_busy(job, busy)


def _error_message(error: AppError | None) -> str:
    return display_error_message(error)


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


def _confirm_csv_import(parent: QWidget, preview: WorkLogCsvImportPreview) -> bool:
    message = _("Import {count} records, replace {existing} existing records, and skip {errors} invalid rows?").format(
        count=len(preview.rows), existing=preview.existing_count, errors=len(preview.errors))
    return QMessageBox.question(parent, _("Import CSV"), message,
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes


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
