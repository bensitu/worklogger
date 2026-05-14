"""Identity query DTOs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ListLinkedIdentitiesQuery:
    user_id: int


@dataclass(frozen=True)
class GetIdentityProvidersQuery:
    user_id: int
