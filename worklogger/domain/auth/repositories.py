"""Authentication repository Protocols."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from worklogger.domain.auth.models import LinkedIdentity, User


class UserRepository(Protocol):
    def get_by_id(self, user_id: int) -> User | None:
        ...

    def get_by_username(self, username: str) -> User | None:
        ...

    def add(self, user: User) -> User:
        ...

    def list_users(self) -> tuple[User, ...]:
        ...


class AuthCredentialRepository(Protocol):
    def user_count(self) -> int:
        ...

    def get_by_id(self, user_id: int) -> User | None:
        ...

    def list_users(self) -> tuple[User, ...]:
        ...

    def create_user(
        self,
        username: str,
        password: str,
        *,
        recovery_key: str | None,
        is_admin: bool,
        must_change_password: bool = False,
    ) -> User:
        ...

    def verify_user(self, username: str, password: str) -> User | None:
        ...

    def change_password(
        self,
        user_id: int,
        current_password: str,
        new_password: str,
    ) -> str | None:
        ...

    def reset_password_with_recovery(
        self,
        username: str,
        recovery_key: str,
        new_password: str,
    ) -> tuple[User, str] | None:
        ...

    def reset_password_by_admin(
        self,
        user_id: int,
        new_password: str,
        *,
        must_change_password: bool,
    ) -> str | None:
        ...

    def set_password_change_required(self, user_id: int, required: bool) -> bool:
        ...

    def delete_user(self, user_id: int) -> bool:
        ...

    def set_remember_token(
        self,
        user_id: int,
        stored_token: str | None,
        expires_at: datetime | None,
    ) -> None:
        ...

    def get_user_by_remember_token(self, stored_token: str) -> User | None:
        ...


class LoginFailureRepository(Protocol):
    def lockout_until(self, username: str) -> datetime | None:
        ...

    def record_failure(self, username: str) -> tuple[int, datetime | None]:
        ...

    def clear_failures(self, username: str) -> None:
        ...


class IdentityRepository(Protocol):
    def list_for_user(self, user_id: int) -> tuple[LinkedIdentity, ...]:
        ...

    def get_by_provider_subject(
        self,
        provider: str,
        subject: str,
    ) -> LinkedIdentity | None:
        ...

    def add(self, identity: LinkedIdentity) -> LinkedIdentity:
        ...

    def remove(self, user_id: int, identity_id: int) -> None:
        ...
