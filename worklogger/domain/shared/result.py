"""Typed result object for predictable error handling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from worklogger.domain.shared.errors import AppError

T = TypeVar("T")


@dataclass(frozen=True)
class Result(Generic[T]):
    ok: bool
    value: T | None = None
    error: AppError | None = None

    def __post_init__(self) -> None:
        if self.ok and self.error is not None:
            raise ValueError("successful Result cannot contain an error")
        if not self.ok and self.error is None:
            raise ValueError("failed Result must contain an error")

    @classmethod
    def success(cls, value: T | None = None) -> "Result[T]":
        return cls(ok=True, value=value)

    @classmethod
    def failure(cls, error: AppError) -> "Result[T]":
        return cls(ok=False, error=error)

