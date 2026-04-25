from __future__ import annotations
from dataclasses import dataclass, replace
from typing import Callable


@dataclass(frozen=True)
class AppState:
    lang: str = "en_US"
    theme: str = "blue"
    custom_color: str | None = None
    dark: bool = False
    work_hours: float = 8.0
    default_break: float = 1.0
    monthly_target: float = 168.0
    show_holidays: bool = True
    show_note_markers: bool = True
    show_overnight_indicator: bool = True
    week_start_monday: bool = False
    time_input_mode: str = "manual"
    minimal_mode: bool = False
    current_user_id: int | None = None
    current_username: str | None = None

    def is_logged_in(self) -> bool:
        return self.current_user_id is not None


class AppStore:
    def __init__(self, initial: AppState | None = None):
        self._state = initial or AppState()
        self._listeners: list[Callable[[AppState], None]] = []

    @property
    def state(self) -> AppState:
        return self._state

    def subscribe(self, listener: Callable[[AppState], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def _unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)
        return _unsubscribe

    def patch(self, **changes) -> AppState:
        self._state = replace(self._state, **changes)
        for listener in list(self._listeners):
            listener(self._state)
        return self._state
