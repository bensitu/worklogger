"""Application event bus contracts."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from threading import RLock
from typing import TypeVar


class AppEvent:
    """Base type for application events."""


@dataclass(frozen=True)
class WorkLogSaved(AppEvent):
    user_id: int
    day: date


@dataclass(frozen=True)
class SettingsChanged(AppEvent):
    user_id: int
    key: str
    value: object


@dataclass(frozen=True)
class ThemeChanged(AppEvent):
    theme: str
    dark: bool


EventT = TypeVar("EventT", bound=AppEvent)
Handler = Callable[[EventT], None]


class EventBus:
    """Synchronous in-process event bus.

    UI adapters may bridge events to Qt signals later. The application bus
    itself has no Qt dependency.
    """

    def __init__(self) -> None:
        self._handlers: dict[type[AppEvent], list[Callable[[AppEvent], None]]] = (
            defaultdict(list)
        )
        self._lock = RLock()

    def subscribe(
        self,
        event_type: type[EventT],
        handler: Handler[EventT],
    ) -> Callable[[], None]:
        with self._lock:
            self._handlers[event_type].append(handler)  # type: ignore[arg-type]

        def unsubscribe() -> None:
            with self._lock:
                handlers = self._handlers.get(event_type, [])
                if handler in handlers:
                    handlers.remove(handler)  # type: ignore[arg-type]

        return unsubscribe

    def publish(self, event: AppEvent) -> None:
        with self._lock:
            handlers = list(self._handlers.get(type(event), []))
        for handler in handlers:
            handler(event)

