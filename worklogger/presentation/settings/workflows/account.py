"""Account settings operations with isolated dependencies."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from worklogger.infrastructure.i18n import _
from worklogger.presentation.auth.dialogs import (
    ChangePasswordDialog,
    ChangePasswordDraft,
)
from worklogger.presentation.settings.workflows.common import (
    _error_message,
    _notify_success,
)
from worklogger.presentation.user_management import UserManagementDialog


class AccountSettingsWorkflow:
    def __init__(
        self,
        *,
        auth_view_model,
        user,
        user_management_view_model,
        remember_session_store,
        change_password_dialog_factory,
        user_management_dialog_factory,
        notify_success,
    ):
        self._auth_view_model = auth_view_model
        self._user = user
        self._user_management_view_model = user_management_view_model
        self._remember_session_store = remember_session_store
        self._change_password_dialog_factory = (
            change_password_dialog_factory or ChangePasswordDialog
        )
        self._user_management_dialog_factory = (
            user_management_dialog_factory or UserManagementDialog
        )
        self._notify_success = notify_success or _notify_success

    def change_password(self, parent: QWidget | None) -> bool:
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

    def manage_users(self, parent: QWidget | None) -> UserManagementDialog:
        assert self._user_management_view_model is not None
        dialog = self._user_management_dialog_factory(
            self._user_management_view_model,
            parent,
        )
        dialog.refresh()
        dialog.exec()
        return dialog
