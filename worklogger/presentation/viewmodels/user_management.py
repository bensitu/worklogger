"""User management presentation ViewModel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from worklogger.app.commands.auth_commands import (
    AdminResetPasswordCommand,
    CreateManagedUserCommand,
    DeleteManagedUserCommand,
    SetPasswordChangeRequiredCommand,
)
from worklogger.app.queries.auth_queries import ListUsersQuery
from worklogger.app.use_cases.auth import RegisteredUser
from worklogger.domain.auth.models import User
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result


class ListUsersHandlerProtocol(Protocol):
    def handle(self, query: ListUsersQuery) -> Result[tuple[User, ...]]:
        ...


class CreateManagedUserHandlerProtocol(Protocol):
    def handle(self, command: CreateManagedUserCommand) -> Result[RegisteredUser]:
        ...


class AdminResetPasswordHandlerProtocol(Protocol):
    def handle(self, command: AdminResetPasswordCommand) -> Result[str]:
        ...


class SetPasswordChangeRequiredHandlerProtocol(Protocol):
    def handle(self, command: SetPasswordChangeRequiredCommand) -> Result[User]:
        ...


class DeleteManagedUserHandlerProtocol(Protocol):
    def handle(self, command: DeleteManagedUserCommand) -> Result[None]:
        ...


@dataclass(frozen=True)
class UserListItem:
    user_id: int
    username: str
    is_admin: bool
    must_change_password: bool


@dataclass(frozen=True)
class UserManagementState:
    users: tuple[UserListItem, ...]


class UserManagementViewModel:
    def __init__(
        self,
        *,
        requesting_user_id: int,
        list_users_handler: ListUsersHandlerProtocol,
        create_user_handler: CreateManagedUserHandlerProtocol,
        reset_password_handler: AdminResetPasswordHandlerProtocol,
        set_password_change_required_handler: SetPasswordChangeRequiredHandlerProtocol,
        delete_user_handler: DeleteManagedUserHandlerProtocol,
    ) -> None:
        self._requesting_user_id = requesting_user_id
        self._list_users_handler = list_users_handler
        self._create_user_handler = create_user_handler
        self._reset_password_handler = reset_password_handler
        self._set_password_change_required_handler = set_password_change_required_handler
        self._delete_user_handler = delete_user_handler

    def load(self) -> Result[UserManagementState]:
        result = self._list_users_handler.handle(
            ListUsersQuery(requesting_user_id=self._requesting_user_id)
        )
        if not result.ok or result.value is None:
            return Result.failure(
                result.error or ValidationError("user_list_failed", "user_list_failed")
            )
        return Result.success(
            UserManagementState(users=tuple(_item_from_user(user) for user in result.value))
        )

    def create_user(
        self,
        *,
        username: str,
        password: str,
        password_confirm: str,
        is_admin: bool,
        must_change_password: bool,
    ) -> Result[RegisteredUser]:
        if password != password_confirm:
            return Result.failure(
                ValidationError("managed_user_password_mismatch", "managed_user_password_mismatch")
            )
        return self._create_user_handler.handle(
            CreateManagedUserCommand(
                requesting_user_id=self._requesting_user_id,
                username=username,
                password=password,
                is_admin=is_admin,
                must_change_password=must_change_password,
            )
        )

    def reset_password(
        self,
        *,
        target_user_id: int,
        new_password: str,
        password_confirm: str,
        must_change_password: bool,
    ) -> Result[str]:
        if new_password != password_confirm:
            return Result.failure(
                ValidationError("managed_user_password_mismatch", "managed_user_password_mismatch")
            )
        return self._reset_password_handler.handle(
            AdminResetPasswordCommand(
                requesting_user_id=self._requesting_user_id,
                target_user_id=target_user_id,
                new_password=new_password,
                must_change_password=must_change_password,
            )
        )

    def set_password_change_required(
        self,
        *,
        target_user_id: int,
        required: bool,
    ) -> Result[UserListItem]:
        result = self._set_password_change_required_handler.handle(
            SetPasswordChangeRequiredCommand(
                requesting_user_id=self._requesting_user_id,
                target_user_id=target_user_id,
                required=required,
            )
        )
        if not result.ok or result.value is None:
            return Result.failure(
                result.error or ValidationError("user_update_failed", "user_update_failed")
            )
        return Result.success(_item_from_user(result.value))

    def delete_user(self, *, target_user_id: int) -> Result[None]:
        return self._delete_user_handler.handle(
            DeleteManagedUserCommand(
                requesting_user_id=self._requesting_user_id,
                target_user_id=target_user_id,
            )
        )


def _item_from_user(user: User) -> UserListItem:
    return UserListItem(
        user_id=user.id,
        username=user.username,
        is_admin=user.is_admin,
        must_change_password=user.must_change_password,
    )
