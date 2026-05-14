"""Identity command DTOs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LoginWithIdentityCommand:
    provider: str
    remember: bool = False


@dataclass(frozen=True)
class LinkIdentityCommand:
    user_id: int
    provider: str
    current_password: str | None = None


@dataclass(frozen=True)
class UnlinkIdentityCommand:
    user_id: int
    identity_id: int
    current_password: str | None = None

