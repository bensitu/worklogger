"""Updates settings operations with isolated dependencies."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from worklogger.__about__ import APP_VERSION
from worklogger.app.job_runner import JobHandle
from worklogger.app.queries.update_queries import CheckForUpdatesQuery
from worklogger.domain.shared.errors import CancellationError
from worklogger.infrastructure.i18n import _
from worklogger.presentation.settings.workflows.common import (
    _error_message,
    _notify_error,
    _notify_success,
    _set_busy,
    _set_status,
    _update_message,
)


class UpdatesSettingsWorkflow:
    def __init__(
        self, *, update_check_handler, job_runner, notify_success, notify_error
    ):
        self._update_check_handler = update_check_handler
        self._job_runner = job_runner
        self._notify_success = notify_success or _notify_success
        self._notify_error = notify_error or _notify_error
        self._update_check_handle = None

    def check_updates(self, dialog: QWidget) -> bool:
        if self._update_check_handler is None:
            _set_status(dialog, _("Update check is not configured."), "update")
            return False
        if self._job_runner is not None:
            if self._update_check_handle is not None:
                _set_status(
                    dialog, _("Please wait for the current update check."), "update"
                )
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
