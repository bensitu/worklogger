"""Shared domain primitives."""

from worklogger.domain.shared.errors import (
    AppError,
    AuthenticationError,
    AuthorizationError,
    CancellationError,
    ConflictError,
    InfrastructureError,
    NotFoundError,
    ValidationError,
)
from worklogger.domain.shared.result import Result

__all__ = [
    "AppError",
    "AuthenticationError",
    "AuthorizationError",
    "CancellationError",
    "ConflictError",
    "InfrastructureError",
    "NotFoundError",
    "Result",
    "ValidationError",
]

