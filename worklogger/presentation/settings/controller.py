"""Settings workflow controller."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QWidget
from shiboken6 import isValid

from worklogger.app.job_runner import JobRunner
from worklogger.app.use_cases.data_portability import WorkLogCsvImportPreview
from worklogger.app.use_cases.updates import CheckForUpdatesHandler
from worklogger.app.use_cases.user_profile import UserProfileService
from worklogger.config.constants import DEFAULT_CLOUD_BACKUP_STARTUP_DELAY_SECONDS
from worklogger.domain.auth.models import User
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import _
from worklogger.presentation.auth.controller import (
    ChangePasswordDialogFactory,
    RememberSessionStore,
)
from worklogger.presentation.help import open_user_guide
from worklogger.presentation.job_runner import shared_job_runner
from worklogger.presentation.settings.dialog import SettingsDialog
from worklogger.presentation.settings.page import SettingsPage
from worklogger.presentation.settings.workflows.account import AccountSettingsWorkflow
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
from worklogger.presentation.settings.workflows.data import DataSettingsWorkflow
from worklogger.presentation.settings.workflows.text_processing import TextProcessingSettingsWorkflow
from worklogger.presentation.settings.workflows.updates import UpdatesSettingsWorkflow
from worklogger.presentation.settings_capabilities import SettingsCapabilities
from worklogger.presentation.user_management import UserManagementDialog
from worklogger.presentation.viewmodels import (
    AuthViewModel,
    DataManagementViewModel,
    LocalModelManagerViewModel,
    SettingsViewModel,
    UserManagementViewModel,
)
from worklogger.presentation.viewmodels.classifications import ClassificationManagerViewModel
from worklogger.presentation.widgets.classification_manager import ClassificationManagerDialog
from worklogger.presentation.widgets.project_manager import ProjectManagerDialog


class SettingsWorkflow(Protocol):
    def open(self, parent: QWidget | None = None) -> SettingsDialog: ...


class LocalModelsWorkflow(Protocol):
    @property
    def view_model(self) -> LocalModelManagerViewModel | None: ...
    def open(self, parent: QWidget | None = None) -> object: ...


class IdentityWorkflow(Protocol):
    def open(self, parent: QWidget | None = None) -> object: ...


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
        csv_confirmation: Callable[[QWidget, WorkLogCsvImportPreview], bool]
        | None = None,
        notify_success: NotificationHandler | None = None,
        notify_error: NotificationHandler | None = None,
        reload_after_restore: ReloadHandler | None = None,
        capabilities: SettingsCapabilities | None = None,
        entry_types_view_model: ClassificationManagerViewModel | None = None,
        work_modes_view_model: ClassificationManagerViewModel | None = None,
        local_inference=None,
        ai_gateway=None,
        ai_connection_test_timeout_seconds: int = 30,
        profile_service: UserProfileService | None = None,
        projects_view_model=None,
        database_path: Path | None = None,
        cloud_backup_service=None,
        cloud_backup_startup_delay_seconds: int = DEFAULT_CLOUD_BACKUP_STARTUP_DELAY_SECONDS,
        cloud_backup_check_interval_seconds: int = 60,
        cloud_backup_retry_initial_seconds: int = 300,
        cloud_backup_retry_max_seconds: int = 3600,
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
        self._entry_types_view_model = entry_types_view_model
        self._work_modes_view_model = work_modes_view_model
        self._profile_service = profile_service
        self._profile_revision = 0
        self._getting_started_handler = None
        self._cloud_workflow = None
        if self._capabilities.cloud_backup_enabled and cloud_backup_service is not None:
            from worklogger.presentation.settings.workflows.cloud_backup import CloudBackupWorkflow
            self._cloud_workflow = CloudBackupWorkflow(cloud_backup_service, job_runner=job_runner,
                startup_delay_seconds=cloud_backup_startup_delay_seconds,
                check_interval_seconds=cloud_backup_check_interval_seconds,
                retry_initial_seconds=cloud_backup_retry_initial_seconds,
                retry_max_seconds=cloud_backup_retry_max_seconds)
        self._projects_view_model = projects_view_model
        self._project_dialog = None
        if local_inference is not None:
            self._capabilities = replace(self._capabilities,
                local_generation=self._capabilities.ai_enabled and local_inference.backend_available)

        self._processing_workflow = TextProcessingSettingsWorkflow(
            settings_view_model=settings_view_model,
            local_models_view_model=local_models_workflow.view_model if local_models_workflow is not None else None,
            capabilities=self._capabilities, job_runner=job_runner,
            local_inference=local_inference, ai_gateway=ai_gateway,
            connection_test_timeout_seconds=ai_connection_test_timeout_seconds,
        )

        self._data_management_view_model = data_management_view_model
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
        return dialog

    def set_restore_handler(self, handler: ReloadHandler) -> None:
        self._data_workflow.set_restore_handler(handler)
        if self._cloud_workflow is not None:
            self._cloud_workflow.set_restore_handler(handler)

    def start_cloud_backups(self, owner):
        if self._cloud_workflow is not None:
            self._cloud_workflow.start(owner)

    def set_getting_started_handler(self, handler):
        self._getting_started_handler = handler

    def _open_getting_started(self, surface):
        if self._getting_started_handler is None or surface.is_busy or not surface.confirm_profile_leave():
            return
        dialog = surface.window()
        if isinstance(dialog, QDialog):
            dialog.accept()
            if dialog.isVisible():
                return
        QTimer.singleShot(0, self._getting_started_handler)

    def create_page(self, parent: QWidget | None = None) -> SettingsPage:
        page = self._page_factory(self._settings_view_model, parent)
        self._bind_surface(page)
        page.refresh()
        return page

    def _bind_surface(self, surface: SettingsPage) -> None:
        surface.set_job_runner(self._job_runner)
        surface.getting_started_button.setEnabled(self._getting_started_handler is not None)
        surface.getting_started_requested.connect(lambda: self._open_getting_started(surface))
        surface.user_guide_requested.connect(open_user_guide)
        if self._cloud_workflow is not None:
            self._cloud_workflow.bind(surface.cloud_backup_panel)
        surface.set_data_directory(self._data_directory)
        surface.open_data_directory_requested.connect(lambda: self._open_data_directory(surface))
        surface.set_profile_available(self._profile_service is not None)
        if self._profile_service is not None:
            surface.profile_save_requested.connect(lambda value, expected: self._save_profile(surface, value, expected))
            surface.profile_refresh_requested.connect(lambda: self._refresh_profile(surface))
        surface.set_entry_types_available(self._entry_types_view_model is not None)
        if self._entry_types_view_model is not None:
            surface.manage_entry_types_requested.connect(lambda: self._manage_classifications(surface))
        surface.set_work_modes_available(self._work_modes_view_model is not None)
        if self._work_modes_view_model is not None:
            surface.manage_work_modes_requested.connect(lambda: self._manage_classifications(surface, work_modes=True))
        surface.set_projects_available(self._projects_view_model is not None)
        if self._projects_view_model is not None:
            surface.manage_projects_requested.connect(lambda: self._manage_projects(surface))
        surface.set_capabilities(self._capabilities)
        surface.set_model_management_available(self._local_models_workflow is not None)
        surface.set_account(self._user)
        surface.set_manage_users_available(self._user_management_view_model is not None and self._user.is_admin)
        surface.set_identity_management_available(self._capabilities.oidc_enabled and self._identity_workflow is not None)
        surface.set_update_check_available(self._update_check_handler is not None)
        surface.change_password_requested.connect(
            lambda: self._change_password(surface)
        )
        if self._user_management_view_model is not None:
            surface.manage_users_requested.connect(lambda: self._manage_users(surface))
        if self._capabilities.oidc_enabled and self._identity_workflow is not None:
            surface.manage_identities_requested.connect(
                lambda: self._identity_workflow.open(surface)
            )
        surface.backup_requested.connect(lambda: self._backup_database(surface))
        surface.check_records_button.setEnabled(bool(getattr(self._data_management_view_model, "can_check_records", False)))
        surface.check_records_requested.connect(lambda: self._check_records(surface))
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
        self._processing_workflow.bind(surface)
        surface.refreshed.connect(lambda: self._processing_workflow.sync(surface))

    def _check_records(self, surface):
        if not getattr(self._data_management_view_model, "can_check_records", False):
            return
        from worklogger.presentation.widgets.record_integrity import RecordIntegrityDialog
        dialog = RecordIntegrityDialog(self._data_management_view_model, surface,
                                       job_runner=self._job_runner)
        dialog.records_changed.connect(surface.records_recovered.emit)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def _open_local_models(self, surface: SettingsPage) -> None:
        if not self._capabilities.ai_enabled or not self._capabilities.model_management or self._local_models_workflow is None:
            return
        self._local_models_workflow.open(surface)
        self._processing_workflow.refresh_models(surface)

    def _manage_classifications(self, surface: SettingsPage, *, work_modes=False) -> None:
        dialog = ClassificationManagerDialog(self._work_modes_view_model if work_modes else self._entry_types_view_model,
            surface, work_modes=work_modes, job_runner=self._job_runner or shared_job_runner())
        dialog.exec()
        dialog.deleteLater()
        surface.entry_types_changed.emit()

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

    def open(self, parent: QWidget | None = None) -> SettingsDialog:
        dialog = self.create_dialog(parent)
        dialog.exec()
        return dialog

    def initialize_processing(self, owner: QWidget, callback: Callable[[], None]) -> None:
        self._processing_workflow.initialize(owner, callback)

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
        return shared_job_runner()

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
