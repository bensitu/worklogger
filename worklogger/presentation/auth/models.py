"""Immutable authentication form drafts without Qt dependencies."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LoginDraft:
    username: str
    password: str = field(repr=False)
    remember: bool


@dataclass(frozen=True)
class RegisterDraft:
    username: str
    password: str = field(repr=False)
    password_confirm: str = field(repr=False)


@dataclass(frozen=True)
class ResetPasswordDraft:
    username: str
    recovery_key: str = field(repr=False)
    new_password: str = field(repr=False)
    password_confirm: str = field(repr=False)


@dataclass(frozen=True)
class ChangePasswordDraft:
    current_password: str = field(repr=False)
    new_password: str = field(repr=False)
    password_confirm: str = field(repr=False)
