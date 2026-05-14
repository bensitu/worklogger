"""Typed application errors."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class AppError:
    code: str
    message: str
    details: Mapping[str, object] = field(default_factory=dict)


class ValidationError(AppError):
    """Input or domain validation failed."""


class AuthenticationError(AppError):
    """Credentials or remembered session are invalid."""


class AuthorizationError(AppError):
    """The current user is not allowed to perform the operation."""


class NotFoundError(AppError):
    """Requested data was not found."""


class ConflictError(AppError):
    """The requested operation conflicts with current state."""


class InfrastructureError(AppError):
    """Technical adapter failure."""


class CancellationError(AppError):
    """The operation was cancelled."""

