"""Settings workflow controller."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Protocol
from pathlib import Path
from weakref import WeakKeyDictionary
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from PySide6.QtWidgets import QWidget
from shiboken6 import isValid

from worklogger.app.job_runner import JobRunner
from worklogger.app.use_cases.data_portability import WorkLogCsvImportPreview
from worklogger.app.use_cases.updates import CheckForUpdatesHandler
from worklogger.domain.auth.models import User
from worklogger.infrastructure.i18n import _
from worklogger.presentation.auth.controller import (
    ChangePasswordDialogFactory,
    RememberSessionStore,
)
from worklogger.presentation.settings.dialog import SettingsDialog
from worklogger.presentation.settings.page import SettingsPage
from worklogger.presentation.settings.workflows.contracts import (
    ConfirmationProvider,
    IcsImportModeProvider,
    NotificationHandler,
    PathProvider,
    ReloadHandler,
    SettingsDialogFactory,
    SettingsPageFactory,
    UserManagementDialogFactory,
)
from worklogger.presentation.settings_capabilities import SettingsCapabilities
from worklogger.presentation.user_management import UserManagementDialog
from worklogger.presentation.viewmodels import (
    AuthViewModel,
    DataManagementViewModel,
    SettingsViewModel,
    UserManagementViewModel,
    LocalModelManagerViewModel,
)


class SettingsWorkflow(Protocol):
    def open(self, parent: QWidget | None = None) -> SettingsDialog: ...


class LocalModelsWorkflow(Protocol):
    @property
    def view_model(self) -> LocalModelManagerViewModel | None: ...
    def open(self, parent: QWidget | None = None) -> object: ...


class IdentityWorkflow(Protocol):
    def open(self, parent: QWidget | None = None) -> object: ...


from worklogger.presentation.settings.workflows.account import AccountSettingsWorkflow
from worklogger.presentation.settings.workflows.common import _error_message
from worklogger.presentation.settings.workflows.data import DataSettingsWorkflow
from worklogger.presentation.settings.workflows.updates import UpdatesSettingsWorkflow
from worklogger.presentation.viewmodels.work_types import WorkTypeManagerViewModel
from worklogger.presentation.widgets.work_type_manager import WorkTypeManagerDialog
from worklogger.presentation.widgets.project_manager import ProjectManagerDialog
from worklogger.app.ports import AIRequest
from worklogger.presentation.job_runner import QtJobRunner, owned_callback
from worklogger.app.use_cases.user_profile import UserProfileService
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.errors import CancellationError
from worklogger.domain.shared.result import Result
from worklogger.presentation.processing import TextProcessingTask


class SettingsWorkflowController:
    def initialize_processing(self, owner, callback):
        def load():
            settings = self._settings_view_model.load()
            model = self._local_models_workflow.view_model if self._local_models_workflow is not None else None
            inventory = model.load() if model is not None else None
            return settings, inventory

        def complete(result):
            if not result.ok:
                return
            settings, inventory = result.value
            if settings.ok and settings.value is not None and self._ai_gateway is not None:
                self._ai_gateway.update_configuration(settings.value)
            if inventory is not None and inventory.ok and self._local_inference is not None:
                self._local_inference.update_inventory(inventory.value.inventory)
            callback()

        if self._job_runner is None:
            complete(Result.success(load()))
        else:
            self._job_runner.submit("initialize_text_processing", lambda _token: load(),
                                    on_complete=owned_callback(owner, complete))

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
        csv_confirmation: Callable[[QWidget, WorkLogCsvImportPreview], bool]
        | None = None,
        notify_success: NotificationHandler | None = None,
        notify_error: NotificationHandler | None = None,
        reload_after_restore: ReloadHandler | None = None,
        capabilities: SettingsCapabilities | None = None,
        work_types_view_model: WorkTypeManagerViewModel | None = None,
        local_inference=None,
        ai_gateway=None,
        profile_service: UserProfileService | None = None,
        projects_view_model=None,
        database_path: Path | None = None,
    ) -> None:
        self._settings_view_model = settings_view_model
        self._data_directory = Path(database_path).resolve().parent if database_path is not None else None
        self._capabilities = capabilities or SettingsCapabilities(
            model_management=local_models_workflow is not None
        )
        self._user = user
        self._update_check_handler = update_check_handler
        self._job_runner = job_runner
        self._identity_workflow = identity_workflow
        self._local_models_workflow = local_models_workflow
        self._user_management_view_model = user_management_view_model
        self._dialog_factory = dialog_factory or SettingsDialog
        self._page_factory = page_factory or SettingsPage
        self._work_types_view_model = work_types_view_model
        self._local_inference = local_inference
        self._ai_gateway = ai_gateway
        self._profile_service = profile_service
        self._profile_revision = 0
        self._projects_view_model = projects_view_model
        self._project_dialog = None
        self._profile_runners: WeakKeyDictionary[SettingsPage, QtJobRunner] = WeakKeyDictionary()
        self._connection_tests: WeakKeyDictionary[SettingsPage, TextProcessingTask] = WeakKeyDictionary()
        if local_inference is not None:
            self._capabilities = replace(self._capabilities, local_generation=local_inference.backend_available)

        self._data_workflow = DataSettingsWorkflow(
            data_management_view_model=data_management_view_model,
            settings_view_model=settings_view_model,
            job_runner=job_runner,
            backup_destination_provider=backup_destination_provider,
            restore_source_provider=restore_source_provider,
            csv_destination_provider=csv_destination_provider,
            csv_source_provider=csv_source_provider,
            ics_destination_provider=ics_destination_provider,
            ics_source_provider=ics_source_provider,
            ics_import_mode_provider=ics_import_mode_provider,
            restore_confirmation=restore_confirmation,
            csv_confirmation=csv_confirmation,
            notify_success=notify_success,
            notify_error=notify_error,
            reload_after_restore=reload_after_restore,
        )
        self._updates_workflow = UpdatesSettingsWorkflow(
            update_check_handler=update_check_handler,
            job_runner=job_runner,
            notify_success=notify_success,
            notify_error=notify_error,
        )
        self._account_workflow = AccountSettingsWorkflow(
            job_runner=job_runner,
            auth_view_model=auth_view_model,
            user=user,
            user_management_view_model=user_management_view_model,
            remember_session_store=remember_session_store,
            change_password_dialog_factory=change_password_dialog_factory,
            user_management_dialog_factory=user_management_dialog_factory,
            notify_success=notify_success,
        )

    def create_dialog(self, parent: QWidget | None = None) -> SettingsDialog:
        dialog = self._dialog_factory(self._settings_view_model, parent)
        self._bind_surface(dialog.page)
        dialog.page.refresh()
        self._sync_inference(dialog.page)
        return dialog

    def set_restore_handler(self, handler: ReloadHandler) -> None:
        self._data_workflow.set_restore_handler(handler)

    def create_page(self, parent: QWidget | None = None) -> SettingsPage:
        page = self._page_factory(self._settings_view_model, parent)
        self._bind_surface(page)
        page.refresh()
        self._sync_inference(page)
        return page

    def _bind_surface(self, surface: SettingsPage) -> None:
        surface.set_data_directory(self._data_directory)
        surface.open_data_directory_requested.connect(lambda: self._open_data_directory(surface))
        surface.set_profile_available(self._profile_service is not None)
        if self._profile_service is not None:
            surface.profile_save_requested.connect(lambda value, expected: self._save_profile(surface, value, expected))
            surface.profile_refresh_requested.connect(lambda: self._refresh_profile(surface))
        if self._local_inference is not None or self._ai_gateway is not None:
            surface.settings_changed.connect(lambda _state: self._sync_inference(surface))
        if self._ai_gateway is not None:
            surface.test_external_model_requested.connect(lambda: self._test_external_model(surface))
        surface.set_work_types_available(self._work_types_view_model is not None)
        if self._work_types_view_model is not None:
            surface.manage_work_types_requested.connect(lambda: self._manage_work_types(surface))
        surface.set_projects_available(self._projects_view_model is not None)
        if self._projects_view_model is not None:
            surface.manage_projects_requested.connect(lambda: self._manage_projects(surface))
        surface.set_capabilities(self._capabilities)
        surface.set_model_management_available(self._local_models_workflow is not None)
        surface.set_account(self._user)
        surface.set_manage_users_available(self._user_management_view_model is not None and self._user.is_admin)
        surface.set_identity_management_available(self._identity_workflow is not None)
        surface.set_update_check_available(self._update_check_handler is not None)
        surface.change_password_requested.connect(
            lambda: self._change_password(surface)
        )
        if self._user_management_view_model is not None:
            surface.manage_users_requested.connect(lambda: self._manage_users(surface))
        if self._identity_workflow is not None:
            surface.manage_identities_requested.connect(
                lambda: self._identity_workflow.open(surface)
            )
        surface.backup_requested.connect(lambda: self._backup_database(surface))
        surface.restore_requested.connect(lambda: self._restore_database(surface))
        surface.export_csv_requested.connect(lambda: self._export_csv(surface))
        surface.import_csv_requested.connect(lambda: self._import_csv(surface))
        surface.import_ics_requested.connect(lambda: self._import_ics(surface))
        surface.export_ics_requested.connect(lambda: self._export_ics(surface))
        surface.update_check_requested.connect(lambda: self._check_updates(surface))
        if self._local_models_workflow is not None:
            surface.manage_local_models_requested.connect(
                lambda: self._open_local_models(surface)
            )
            self._refresh_local_models_status(surface)

    def _open_local_models(self, surface: SettingsPage) -> None:
        self._local_models_workflow.open(surface)
        self._refresh_local_models_status(surface)

    def _manage_work_types(self, surface: SettingsPage) -> None:
        dialog = WorkTypeManagerDialog(self._work_types_view_model, surface)
        dialog.exec()
        dialog.deleteLater()
        surface.work_types_changed.emit()

    def _manage_projects(self, surface: SettingsPage):
        if self._project_dialog is not None and isValid(self._project_dialog):
            self._project_dialog.raise_()
            self._project_dialog.activateWindow()
            return
        dialog = ProjectManagerDialog(self._projects_view_model, surface, job_runner=self._job_runner)
        self._project_dialog = dialog
        dialog.changed.connect(surface.projects_changed.emit)
        dialog.finished.connect(lambda: setattr(self, "_project_dialog", None))
        dialog.finished.connect(dialog.deleteLater)
        dialog.open()

    def _open_data_directory(self, surface: SettingsPage):
        if self._data_directory is None or not self._data_directory.is_dir():
            self._data_workflow._notify_error(surface, _("Data location"), _("The data directory is unavailable."))
            return False
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._data_directory))):
            self._data_workflow._notify_error(surface, _("Data location"), _("Unable to open the data directory."))
            return False
        return True

    def _refresh_local_models_status(self, surface: SettingsPage) -> None:
        view_model = self._local_models_workflow.view_model if self._local_models_workflow is not None else None
        if view_model is None:
            return

        def complete(result: object) -> None:
            if not isValid(surface):
                return
            if not result.ok or result.value is None:
                surface.set_local_model_error(result.error)
                return
            inventory = result.value.inventory
            if self._local_inference is not None:
                if self._local_inference.update_inventory(inventory) is False:
                    self._refresh_local_models_status(surface)
                    return
            active = next(
                (
                    item
                    for item in inventory.items
                    if item.entry.id == inventory.active_model_id
                ),
                None,
            )
            surface.set_local_model_status(
                ready=active is not None and active.verified,
                name=active.entry.display_name if active is not None else "",
            )
            surface.set_local_model_context_limit(active.entry.context_length if active is not None else None)
            self._sync_inference(surface)

        if self._job_runner is None:
            complete(view_model.load())
        else:
            self._job_runner.submit(
                "local_model_status",
                lambda _token: view_model.load(),
                on_complete=complete,
            )

    def open(self, parent: QWidget | None = None) -> SettingsDialog:
        dialog = self.create_dialog(parent)
        dialog.exec()
        return dialog

    def _sync_inference(self, surface: SettingsPage):
        if self._ai_gateway is not None and surface.state is not None:
            self._ai_gateway.update_configuration(surface.state)
        if self._local_inference is not None:
            surface.set_local_runtime_status(ready=self._local_inference.available, reason=self._local_inference.reason)
        if self._local_inference is not None or self._ai_gateway is not None:
            surface.ai_availability_changed.emit()

    def _refresh_profile(self, surface: SettingsPage):
        if surface.is_busy:
            return
        self._profile_revision += 1
        revision = self._profile_revision
        def complete(result):
            if not isValid(surface) or revision != self._profile_revision:
                return
            if result.ok and result.value is not None:
                self._apply_profile(surface, result.value)
            else:
                surface.set_profile_error(result.error)
        runner = self._profile_runner(surface)
        try:
            runner.submit("load_user_profile", lambda _token: self._profile_service.load(), on_complete=complete)
        except Exception:
            complete(Result.failure(InfrastructureError("user_profile_load_failed", "user_profile_load_failed")))

    def _apply_profile(self, surface: SettingsPage, user: User):
        self._user = user
        surface.set_account(user)
        surface.profile_changed.emit(user)

    def _profile_runner(self, surface: SettingsPage):
        if self._job_runner is not None:
            return self._job_runner
        runner = self._profile_runners.get(surface)
        if runner is None:
            runner = QtJobRunner(surface)
            self._profile_runners[surface] = runner
            surface.destroyed.connect(lambda: self._profile_runners.pop(surface, None))
        return runner

    def _save_profile(self, surface: SettingsPage, value: str, expected: str):
        if surface.is_busy:
            return
        self._profile_revision += 1
        surface.set_profile_busy(True)
        def complete(result):
            if not isValid(surface):
                return
            surface.set_profile_busy(False)
            if result.ok and result.value is not None:
                surface.complete_profile_save(result.value)
                self._apply_profile(surface, result.value)
            else:
                surface.set_profile_error(result.error)
                if result.error is not None and result.error.code == "user_profile_conflict":
                    self._refresh_profile(surface)
        runner = self._profile_runner(surface)
        try:
            runner.submit("save_user_profile", lambda _token: self._profile_service.save_display_name(
                value, expected_display_name=expected), on_complete=complete)
        except Exception:
            complete(Result.failure(InfrastructureError("user_profile_save_failed", "user_profile_save_failed")))

    def _test_external_model(self, surface: SettingsPage):
        if surface.is_busy or self._ai_gateway is None:
            return
        surface.set_busy("external_model_test", True)
        surface.set_external_test_status("")
        task = self._connection_tests.get(surface)
        if task is None:
            task = TextProcessingTask(surface, job_runner=self._job_runner)
            self._connection_tests[surface] = task
            surface.destroyed.connect(lambda: self._connection_tests.pop(surface, None))
            surface.bind_external_test_progress(task)
        def complete(result):
            if not isValid(surface):
                return
            surface.set_busy("external_model_test", False)
            surface.set_external_test_status(_("Connection succeeded.") if result.ok else
                _("Operation cancelled.") if isinstance(result.error, CancellationError) else _error_message(result.error))
        task.run("test_external_model", lambda _token: self._ai_gateway.generate(AIRequest(
            messages=({"role": "user", "content": "Reply with OK."},), model="default", timeout_seconds=30)), on_complete=complete)

    def _change_password(self, parent: QWidget | None) -> bool:
        return self._account_workflow.change_password(parent)

    def _manage_users(self, parent: QWidget | None) -> UserManagementDialog | None:
        return self._account_workflow.manage_users(parent)

    def _backup_database(self, dialog: QWidget) -> bool:
        return self._data_workflow.backup_database(dialog)

    def _restore_database(self, dialog: QWidget) -> bool:
        return self._data_workflow.restore_database(dialog)

    def _export_csv(self, dialog: QWidget) -> bool:
        return self._data_workflow.export_csv(dialog)

    def _import_csv(self, dialog: QWidget) -> bool:
        return self._data_workflow.import_csv(dialog)

    def _export_ics(self, dialog: QWidget) -> bool:
        return self._data_workflow.export_ics(dialog)

    def _import_ics(self, dialog: QWidget) -> bool:
        return self._data_workflow.import_ics(dialog)

    def _check_updates(self, dialog: QWidget) -> bool:
        return self._updates_workflow.check_updates(dialog)
