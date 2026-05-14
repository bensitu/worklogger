"""Authentication flow controller."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Protocol

from PySide6.QtWidgets import QWidget

from worklogger.domain.auth.models import User
from worklogger.domain.shared.errors import AppError, CancellationError, ValidationError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import _
from worklogger.presentation.auth.dialogs import (
    ChangePasswordDialog,
    ChangePasswordDraft,
    LoginDialog,
    LoginDraft,
    RegisterDialog,
    RegisterDraft,
    ResetPasswordDialog,
    ResetPasswordDraft,
)
from worklogger.presentation.viewmodels import AuthViewModel

ChangePasswordDialogFactory = Callable[[QWidget | None], ChangePasswordDialog]
LoginDialogFactory = Callable[[QWidget | None], LoginDialog]
RegisterDialogFactory = Callable[[QWidget | None], RegisterDialog]
ResetPasswordDialogFactory = Callable[[QWidget | None], ResetPasswordDialog]


@dataclass(frozen=True)
class AuthSession:
    user: User
    remember_token: str | None = None
    recovery_key: str | None = None


class RememberSessionStore(Protocol):
    def load_token(self) -> Result[str | None]:
        ...

    def save_token(self, token: str) -> Result[None]:
        ...

    def clear_token(self) -> Result[None]:
        ...


@dataclass
class _AuthDialogOutcome:
    session: AuthSession | None = None
    next_mode: str | None = None
    accepted: bool = False


class AuthController:
    def __init__(
        self,
        view_model: AuthViewModel,
        *,
        parent: QWidget | None = None,
        change_password_dialog_factory: ChangePasswordDialogFactory | None = None,
        login_dialog_factory: LoginDialogFactory | None = None,
        register_dialog_factory: RegisterDialogFactory | None = None,
        remember_session_store: RememberSessionStore | None = None,
        reset_password_dialog_factory: ResetPasswordDialogFactory | None = None,
    ) -> None:
        self._view_model = view_model
        self._parent = parent
        self._change_password_dialog_factory = (
            change_password_dialog_factory or ChangePasswordDialog
        )
        self._login_dialog_factory = login_dialog_factory or LoginDialog
        self._register_dialog_factory = register_dialog_factory or RegisterDialog
        self._remember_session_store = remember_session_store
        self._reset_password_dialog_factory = (
            reset_password_dialog_factory or ResetPasswordDialog
        )

    def authenticate(self) -> Result[AuthSession]:
        remembered = self._authenticate_remembered_session()
        if remembered.ok and remembered.value is not None:
            return remembered

        mode = self._view_model.mode()
        if not mode.ok or mode.value is None:
            return Result.failure(
                mode.error or ValidationError("auth_state_failed", "auth_state_failed")
            )

        current_mode = mode.value.mode
        while True:
            if current_mode == "register":
                outcome = self._run_register_dialog()
            elif current_mode == "reset":
                outcome = self._run_reset_password_dialog()
            else:
                outcome = self._run_login_dialog()
            if outcome.accepted and outcome.session is not None:
                return Result.success(outcome.session)
            if outcome.next_mode is not None:
                current_mode = outcome.next_mode
                continue
            return Result.failure(CancellationError("auth_cancelled", "auth_cancelled"))

    def _run_login_dialog(self) -> _AuthDialogOutcome:
        dialog = self._login_dialog_factory(self._parent)
        outcome = _AuthDialogOutcome()

        def submit(draft: LoginDraft) -> None:
            dialog.set_busy(True)
            result = self._view_model.login(
                username=draft.username,
                password=draft.password,
                remember=draft.remember,
            )
            dialog.set_busy(False)
            if not result.ok or result.value is None:
                dialog.set_error(_error_message(result.error))
                return
            outcome.session = AuthSession(
                user=result.value.user,
                remember_token=result.value.token,
            )
            if result.value.user.must_change_password:
                change_outcome = self._run_change_password_dialog(result.value.user)
                if not change_outcome.accepted or change_outcome.session is None:
                    dialog.set_error(_("Password change required."))
                    return
                outcome.session = change_outcome.session
                self._clear_remembered_session()
            elif result.value.token:
                self._save_remembered_session(result.value.token)
            else:
                self._clear_remembered_session()
            outcome.accepted = True
            dialog.accept()

        def switch_to_register() -> None:
            outcome.next_mode = "register"
            dialog.reject()

        def switch_to_reset() -> None:
            outcome.next_mode = "reset"
            dialog.reject()

        dialog.login_submitted.connect(submit)
        dialog.register_requested.connect(switch_to_register)
        dialog.reset_password_requested.connect(switch_to_reset)
        dialog.exec()
        return outcome

    def clear_remembered_session(self) -> Result[None]:
        if self._remember_session_store is None:
            return Result.success(None)
        return self._remember_session_store.clear_token()

    def _authenticate_remembered_session(self) -> Result[AuthSession | None]:
        if self._remember_session_store is None:
            return Result.success(None)
        token = self._remember_session_store.load_token()
        if not token.ok:
            self._remember_session_store.clear_token()
            return Result.success(None)
        if not token.value:
            return Result.success(None)
        user = self._view_model.login_with_remember_token(token.value)
        if not user.ok or user.value is None:
            self._remember_session_store.clear_token()
            return Result.success(None)
        if user.value.must_change_password:
            self._remember_session_store.clear_token()
            return Result.success(None)
        return Result.success(AuthSession(user=user.value, remember_token=token.value))

    def _save_remembered_session(self, token: str) -> None:
        if self._remember_session_store is not None:
            self._remember_session_store.save_token(token)

    def _clear_remembered_session(self) -> None:
        if self._remember_session_store is not None:
            self._remember_session_store.clear_token()

    def _run_register_dialog(self) -> _AuthDialogOutcome:
        dialog = self._register_dialog_factory(self._parent)
        outcome = _AuthDialogOutcome()

        def submit(draft: RegisterDraft) -> None:
            dialog.set_busy(True)
            result = self._view_model.register(
                username=draft.username,
                password=draft.password,
                password_confirm=draft.password_confirm,
            )
            dialog.set_busy(False)
            if not result.ok or result.value is None:
                dialog.set_error(_error_message(result.error))
                return
            outcome.session = AuthSession(
                user=result.value.user,
                recovery_key=result.value.recovery_key,
            )
            dialog.set_error(_("Save this recovery key before continuing."))
            dialog.mark_complete(result.value.recovery_key)

        def continue_to_app() -> None:
            outcome.accepted = outcome.session is not None
            if outcome.accepted:
                dialog.accept()

        def switch_to_login() -> None:
            outcome.next_mode = "login"
            dialog.reject()

        dialog.register_submitted.connect(submit)
        dialog.continue_requested.connect(continue_to_app)
        dialog.login_requested.connect(switch_to_login)
        dialog.exec()
        return outcome

    def _run_reset_password_dialog(self) -> _AuthDialogOutcome:
        dialog = self._reset_password_dialog_factory(self._parent)
        outcome = _AuthDialogOutcome()

        def submit(draft: ResetPasswordDraft) -> None:
            dialog.set_busy(True)
            result = self._view_model.reset_password(
                username=draft.username,
                recovery_key=draft.recovery_key,
                new_password=draft.new_password,
                password_confirm=draft.password_confirm,
            )
            dialog.set_busy(False)
            if not result.ok or result.value is None:
                dialog.set_error(_error_message(result.error))
                return
            dialog.set_error(_("Save this recovery key before returning to login."))
            dialog.mark_complete(result.value)

        def continue_to_login() -> None:
            outcome.next_mode = "login"
            dialog.accept()

        def switch_to_login() -> None:
            outcome.next_mode = "login"
            dialog.reject()

        dialog.reset_submitted.connect(submit)
        dialog.continue_requested.connect(continue_to_login)
        dialog.login_requested.connect(switch_to_login)
        dialog.exec()
        return outcome

    def _run_change_password_dialog(self, user: User) -> _AuthDialogOutcome:
        dialog = self._change_password_dialog_factory(self._parent)
        outcome = _AuthDialogOutcome()

        def submit(draft: ChangePasswordDraft) -> None:
            dialog.set_busy(True)
            result = self._view_model.change_password(
                user_id=user.id,
                current_password=draft.current_password,
                new_password=draft.new_password,
                password_confirm=draft.password_confirm,
            )
            dialog.set_busy(False)
            if not result.ok or result.value is None:
                dialog.set_error(_error_message(result.error))
                return
            outcome.session = AuthSession(
                user=replace(user, must_change_password=False),
                recovery_key=result.value,
            )
            dialog.set_error(_("Save this recovery key before continuing."))
            dialog.mark_complete(result.value)

        def continue_to_app() -> None:
            outcome.accepted = outcome.session is not None
            if outcome.accepted:
                dialog.accept()

        dialog.change_submitted.connect(submit)
        dialog.continue_requested.connect(continue_to_app)
        dialog.exec()
        return outcome


def _error_message(error: AppError | None) -> str:
    return error.message if error is not None else _("Unknown error")
