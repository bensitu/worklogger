"""Authentication domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class User:
    id: int
    username: str
    is_admin: bool = False
    must_change_password: bool = False
    created_at: datetime | None = None
    password_changed_at: datetime | None = None
    recovery_key_created_at: datetime | None = None
    last_login_at: datetime | None = None


@dataclass(frozen=True)
class LinkedIdentity:
    id: int
    user_id: int
    provider: str
    subject: str
    email: str | None = None
    display_name: str | None = None


@dataclass(frozen=True)
class RememberedLogin:
    user: User
    token: str | None = None
