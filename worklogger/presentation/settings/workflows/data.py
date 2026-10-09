"""Data settings operations with isolated dependencies."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import QWidget
from shiboken6 import isValid

from worklogger.app.job_runner import JobHandle
from worklogger.app.use_cases.data_portability import WorkLogCsvImportPreview
from worklogger.domain.shared.errors import AppError, CancellationError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import _
from worklogger.presentation.settings.workflows.common import (
    _backup_destination,
    _choose_ics_import_mode,
    _confirm_csv_import,
    _confirm_restore,
    _csv_destination,
    _csv_source,
    _error_message,
    _ics_destination,
    _ics_source,
    _notify_error,
    _notify_success,
    _restore_source,
    _set_busy,
    _set_status,
)
from worklogger.presentation.viewmodels import (
    DataManagementActionState,
)


class DataSettingsWorkflow:
    def __init__(
        self,
        *,
        data_management_view_model,
        settings_view_model,
        job_runner,
        backup_destination_provider,
        restore_source_provider,
        csv_destination_provider,
        csv_source_provider,
        ics_destination_provider,
        ics_source_provider,
        ics_import_mode_provider,
        restore_confirmation,
        csv_confirmation,
        notify_success,
        notify_error,
        reload_after_restore,
    ):
        self._data_management_view_model = data_management_view_model
        self._settings_view_model = settings_view_model
        self._job_runner = job_runner
        self._backup_destination_provider = (
            backup_destination_provider or _backup_destination
        )
        self._restore_source_provider = restore_source_provider or _restore_source
        self._csv_destination_provider = csv_destination_provider or _csv_destination
        self._csv_source_provider = csv_source_provider or _csv_source
        self._ics_destination_provider = ics_destination_provider or _ics_destination
        self._ics_source_provider = ics_source_provider or _ics_source
        self._ics_import_mode_provider = (
            ics_import_mode_provider or _choose_ics_import_mode
        )
        self._restore_confirmation = restore_confirmation or _confirm_restore
        self._csv_confirmation = csv_confirmation or _confirm_csv_import
        self._notify_success = notify_success or _notify_success
        self._notify_error = notify_error or _notify_error
        self._reload_after_restore = reload_after_restore
        self._data_job_handle = None
        self._restore_validation_handle = None

    def set_restore_handler(self, handler):
        self._reload_after_restore = handler

    def backup_database(self, dialog: QWidget) -> bool:
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

    def restore_database(self, dialog: QWidget) -> bool:
        if (
            self._data_job_handle is not None
            or self._restore_validation_handle is not None
        ):
            _set_status(dialog, _("Please wait for the current data operation."))
            return False
        path = self._restore_source_provider(dialog)
        if path is None:
            _set_status(dialog, _("Restore cancelled"))
            return False
        if self._job_runner is not None:
            _set_status(dialog, _("Validating backup..."))
            _set_busy(dialog, "data", True)
            self._restore_validation_handle = JobHandle(
                job_id="restore_validate_pending", cancel=lambda: None
            )
            handle = self._job_runner.submit(
                "restore_validate",
                lambda _token: (
                    self._data_management_view_model.validate_restore_database(path)
                ),
                on_complete=lambda result: self._restore_validated(
                    dialog, path, result
                ),
            )
            if self._restore_validation_handle is not None:
                self._restore_validation_handle = handle
            return True
        return self._restore_validated(
            dialog,
            path,
            self._data_management_view_model.validate_restore_database(path),
        )

    def _restore_validated(
        self, dialog: QWidget, path: Path, validation: object
    ) -> bool:
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
        if (
            restored
            and self._job_runner is None
            and self._reload_after_restore is not None
        ):
            self._reload_after_restore()
        return restored

    def export_csv(self, dialog: QWidget) -> bool:
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

    def import_csv(self, dialog: QWidget) -> bool:
        if (
            self._data_job_handle is not None
            or self._restore_validation_handle is not None
        ):
            _set_status(dialog, _("Please wait for the current data operation."))
            return False
        path = self._csv_source_provider(dialog)
        if path is None:
            _set_status(dialog, _("Import cancelled"))
            return False
        if self._job_runner is None:
            return self._complete_csv_preview(
                dialog, path, self._data_management_view_model.preview_csv(path)
            )
        _set_busy(dialog, "data", True)
        self._data_job_handle = JobHandle(
            job_id="csv_preview_pending", cancel=lambda: None
        )
        handle = self._job_runner.submit(
            "csv_preview",
            lambda _token: self._data_management_view_model.preview_csv(path),
            on_complete=lambda result: self._complete_csv_preview(dialog, path, result),
        )
        if self._data_job_handle is not None:
            self._data_job_handle = handle
        return True

    def _complete_csv_preview(
        self, dialog: QWidget, path: Path, result: Result[WorkLogCsvImportPreview]
    ) -> bool:
        self._data_job_handle = None
        if not isValid(dialog):
            return False
        _set_busy(dialog, "data", False)
        if not result.ok or result.value is None:
            return self._handle_data_result(
                dialog, _("Import CSV"), Result.failure(result.error), lambda _state: ""
            )
        preview = result.value
        if not self._csv_confirmation(dialog, preview):
            _set_status(dialog, _("Import cancelled"))
            return False
        return self._run_data_job(
            dialog,
            _("Import CSV"),
            lambda: self._data_management_view_model.import_csv(
                path, preview=preview, overwrite=preview.existing_count > 0
            ),
            lambda state: _("Imported {count} records.").format(
                count=state.record_count
            ),
            _("Importing CSV..."),
        )

    def export_ics(self, dialog: QWidget) -> bool:
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

    def import_ics(self, dialog: QWidget) -> bool:
        path = self._ics_source_provider(dialog)
        if path is None:
            _set_status(dialog, _("Import cancelled"))
            return False
        count = self._data_management_view_model.calendar_event_count()
        if not count.ok or count.value is None:
            return self._handle_data_result(
                dialog,
                _("Import .ics"),
                Result.failure(
                    count.error or AppError("ics_import_failed", "ics_import_failed")
                ),
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
                if (
                    loaded.ok
                    and loaded.value is not None
                    and hasattr(dialog, "set_backup_time")
                ):
                    dialog.set_backup_time(loaded.value.last_backup_at)
            else:
                message += "\n" + _(
                    "Backup succeeded, but its timestamp could not be saved."
                )
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
        if (
            self._data_job_handle is not None
            or self._restore_validation_handle is not None
        ):
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
