"""Authentication command DTOs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RegisterUserCommand:
    username: str
    password: str
    is_admin: bool = False
    recovery_key: str | None = None
    must_change_password: bool = False


@dataclass(frozen=True)
class LoginCommand:
    username: str
    password: str
    remember: bool = False


@dataclass(frozen=True)
class ChangePasswordCommand:
    user_id: int
    current_password: str | None
    new_password: str


@dataclass(frozen=True)
class ResetPasswordCommand:
    username: str
    recovery_key: str
    new_password: str


@dataclass(frozen=True)
class CreateManagedUserCommand:
    requesting_user_id: int
    username: str
    password: str
    is_admin: bool = False
    must_change_password: bool = True


@dataclass(frozen=True)
class AdminResetPasswordCommand:
    requesting_user_id: int
    target_user_id: int
    new_password: str
    must_change_password: bool = True


@dataclass(frozen=True)
class SetPasswordChangeRequiredCommand:
    requesting_user_id: int
    target_user_id: int
    required: bool


@dataclass(frozen=True)
class DeleteManagedUserCommand:
    requesting_user_id: int
    target_user_id: int
