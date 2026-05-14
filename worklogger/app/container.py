"""Small explicit dependency container."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")
Provider = Callable[["AppContainer"], Any]


class DependencyNotRegisteredError(LookupError):
    """Raised when resolving an unknown dependency token."""


class AppContainer:
    """Manual dependency container with explicit registrations.

    The container is intentionally small. It stores objects by caller-provided
    tokens, usually Protocol or concrete types, and avoids import-time global
    service construction.
    """

    def __init__(self) -> None:
        self._providers: dict[object, tuple[Provider, bool]] = {}
        self._singletons: dict[object, Any] = {}

    def register_instance(self, token: object, instance: Any) -> None:
        self._singletons[token] = instance

    def register_factory(
        self,
        token: object,
        factory: Provider,
        *,
        singleton: bool = False,
    ) -> None:
        self._providers[token] = (factory, singleton)
        self._singletons.pop(token, None)

    def resolve(self, token: object) -> Any:
        if token in self._singletons:
            return self._singletons[token]
        provider_entry = self._providers.get(token)
        if provider_entry is None:
            raise DependencyNotRegisteredError(f"No dependency registered for {token!r}")
        provider, singleton = provider_entry
        instance = provider(self)
        if singleton:
            self._singletons[token] = instance
        return instance

