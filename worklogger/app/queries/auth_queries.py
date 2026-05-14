"""Authentication query DTOs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ListUsersQuery:
    requesting_user_id: int
