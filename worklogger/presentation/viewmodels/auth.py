"""Authentication presentation ViewModel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from worklogger.app.commands.auth_commands import (
    ChangePasswordCommand,
    LoginCommand,
    RegisterUserCommand,
    ResetPasswordCommand,
)
from worklogger.app.use_cases.auth import AuthBootstrapState, RegisteredUser
from worklogger.domain.auth.models import RememberedLogin, User
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result


class AuthStateHandler(Protocol):
    def handle(self) -> Result[AuthBootstrapState]:
        ...


class AuthLoginHandler(Protocol):
    def handle(self, command: LoginCommand) -> Result[RememberedLogin]:
        ...


class AuthRegisterHandler(Protocol):
    def handle(self, command: RegisterUserCommand) -> Result[RegisteredUser]:
        ...


class AuthChangePasswordHandler(Protocol):
    def handle(self, command: ChangePasswordCommand) -> Result[str]:
        ...


class AuthResetPasswordHandler(Protocol):
    def handle(self, command: ResetPasswordCommand) -> Result[str]:
        ...


class AuthRememberTokenHandler(Protocol):
    def handle(self, token: str) -> Result[User]:
        ...


@dataclass(frozen=True)
class AuthModeState:
    mode: str
    has_users: bool


class AuthViewModel:
    def __init__(
        self,
        *,
        state_handler: AuthStateHandler,
        login_handler: AuthLoginHandler,
        register_handler: AuthRegisterHandler,
        change_password_handler: AuthChangePasswordHandler | None = None,
        remember_token_handler: AuthRememberTokenHandler | None = None,
        reset_password_handler: AuthResetPasswordHandler | None = None,
    ) -> None:
        self._state_handler = state_handler
        self._login_handler = login_handler
        self._register_handler = register_handler
        self._change_password_handler = change_password_handler
        self._remember_token_handler = remember_token_handler
        self._reset_password_handler = reset_password_handler

    def mode(self) -> Result[AuthModeState]:
        state = self._state_handler.handle()
        if not state.ok or state.value is None:
            return Result.failure(
                state.error or ValidationError("auth_state_failed", "auth_state_failed")
            )
        mode = "login" if state.value.has_users else "register"
        return Result.success(AuthModeState(mode=mode, has_users=state.value.has_users))

    def login(
        self,
        *,
        username: str,
        password: str,
        remember: bool = False,
    ) -> Result[RememberedLogin]:
        return self._login_handler.handle(
            LoginCommand(username=username, password=password, remember=remember)
        )

    def login_with_remember_token(self, token: str) -> Result[User]:
        if self._remember_token_handler is None:
            return Result.failure(
                ValidationError(
                    "remember_login_unavailable",
                    "remember_login_unavailable",
                )
            )
        return self._remember_token_handler.handle(token)

    def register(
        self,
        *,
        username: str,
        password: str,
        password_confirm: str,
    ) -> Result[RegisteredUser]:
        if password != password_confirm:
            return Result.failure(
                ValidationError(
                    "registration_password_mismatch",
                    "registration_password_mismatch",
                )
            )
        return self._register_handler.handle(
            RegisterUserCommand(username=username, password=password)
        )

    def change_password(
        self,
        *,
        user_id: int,
        current_password: str,
        new_password: str,
        password_confirm: str,
    ) -> Result[str]:
        if new_password != password_confirm:
            return Result.failure(
                ValidationError(
                    "password_change_mismatch",
                    "password_change_mismatch",
                )
            )
        if self._change_password_handler is None:
            return Result.failure(
                ValidationError(
                    "password_change_unavailable",
                    "password_change_unavailable",
                )
            )
        return self._change_password_handler.handle(
            ChangePasswordCommand(
                user_id=user_id,
                current_password=current_password,
                new_password=new_password,
            )
        )

    def reset_password(
        self,
        *,
        username: str,
        recovery_key: str,
        new_password: str,
        password_confirm: str,
    ) -> Result[str]:
        if new_password != password_confirm:
            return Result.failure(
                ValidationError(
                    "password_reset_mismatch",
                    "password_reset_mismatch",
                )
            )
        if self._reset_password_handler is None:
            return Result.failure(
                ValidationError(
                    "password_reset_unavailable",
                    "password_reset_unavailable",
                )
            )
        return self._reset_password_handler.handle(
            ResetPasswordCommand(
                username=username,
                recovery_key=recovery_key,
                new_password=new_password,
            )
        )
