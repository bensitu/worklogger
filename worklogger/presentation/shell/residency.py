"""Tray and menu-bar residency presentation state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import sys
from typing import Protocol

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon, QWidget

from worklogger.app.commands.settings_commands import SetSettingCommand
from worklogger.app.queries.settings_queries import GetSettingQuery
from worklogger.config.constants import (
    ENABLE_MENU_BAR_SETTING_KEY,
    ENABLE_TRAY_SETTING_KEY,
)
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import _


class ResidencyGetHandler(Protocol):
    def handle(self, query: GetSettingQuery) -> Result[str | None]:
        ...


class ResidencySetHandler(Protocol):
    def handle(self, command: SetSettingCommand) -> Result[None]:
        ...


@dataclass(frozen=True)
class ResidencyState:
    platform: str
    setting_key: str | None
    available: bool
    enabled: bool

    @property
    def keep_resident(self) -> bool:
        return self.available and self.enabled


class ResidencyViewModel:
    def __init__(
        self,
        *,
        user_id: int,
        get_handler: ResidencyGetHandler,
        set_handler: ResidencySetHandler,
        platform: str | None = None,
        availability_probe: Callable[[], bool] | None = None,
    ) -> None:
        self._user_id = user_id
        self._get_handler = get_handler
        self._set_handler = set_handler
        self._platform = platform or sys.platform
        self._availability_probe = availability_probe or (lambda: True)

    def load(self) -> Result[ResidencyState]:
        key = residency_setting_key(self._platform)
        available = bool(key and self._availability_probe())
        if key is None:
            return Result.success(
                ResidencyState(
                    platform=self._platform,
                    setting_key=None,
                    available=False,
                    enabled=False,
                )
            )
        value = self._get_handler.handle(GetSettingQuery(self._user_id, key, "0"))
        if not value.ok:
            return Result.failure(value.error or _error("residency_load_failed"))
        return Result.success(
            ResidencyState(
                platform=self._platform,
                setting_key=key,
                available=available,
                enabled=available and _bool(value.value),
            )
        )

    def set_enabled(self, enabled: bool) -> Result[ResidencyState]:
        key = residency_setting_key(self._platform)
        if key is None:
            return Result.failure(_error("residency_unavailable"))
        result = self._set_handler.handle(
            SetSettingCommand(
                user_id=self._user_id,
                key=key,
                value="1" if enabled else "0",
            )
        )
        if not result.ok:
            return Result.failure(result.error or _error("residency_save_failed"))
        return self.load()


def residency_setting_key(platform: str | None = None) -> str | None:
    value = str(platform or sys.platform).lower()
    if value.startswith("win"):
        return ENABLE_TRAY_SETTING_KEY
    if value == "darwin":
        return ENABLE_MENU_BAR_SETTING_KEY
    return None


def _bool(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _error(code: str) -> ValidationError:
    return ValidationError(code, code)


class QtResidencyController:
    def __init__(
        self,
        view_model: ResidencyViewModel,
        *,
        application: QApplication | None = None,
        tray_available: Callable[[], bool] | None = None,
    ) -> None:
        self._view_model = view_model
        self._application = application or QApplication.instance()
        self._tray_available = tray_available or QSystemTrayIcon.isSystemTrayAvailable
        self._tray_icon: QSystemTrayIcon | None = None
        self._quit_requested = False
        self._last_keep_resident = False

    @property
    def quit_requested(self) -> bool:
        return self._quit_requested

    def attach(
        self,
        parent: QWidget,
        *,
        open_callback: Callable[[], None] | None = None,
        quit_callback: Callable[[], None] | None = None,
    ) -> None:
        if self._tray_icon is None and self._tray_available():
            icon = parent.windowIcon()
            if icon.isNull():
                icon = parent.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
            self._tray_icon = QSystemTrayIcon(icon, parent)
            menu = QMenu(parent)
            open_action = QAction(_("Open"), parent)
            open_action.triggered.connect(open_callback or parent.show)
            quit_action = QAction(_("Quit"), parent)
            quit_action.triggered.connect(quit_callback or self.request_quit)
            menu.addAction(open_action)
            menu.addSeparator()
            menu.addAction(quit_action)
            self._tray_icon.setContextMenu(menu)
            self._tray_icon.activated.connect(
                lambda reason: self._handle_activated(reason, open_callback or parent.show)
            )
        self.refresh()

    def refresh(self) -> ResidencyState | None:
        state = self._view_model.load()
        if not state.ok or state.value is None:
            self._last_keep_resident = False
            self._set_quit_on_last_window_closed(True)
            return None
        self._last_keep_resident = bool(
            state.value.keep_resident and self._tray_available()
        )
        self._set_quit_on_last_window_closed(not self._last_keep_resident)
        if self._tray_icon is not None:
            self._tray_icon.setToolTip(_("WorkLogger"))
            if self._last_keep_resident:
                self._tray_icon.show()
            else:
                self._tray_icon.hide()
        return state.value

    def should_keep_resident(self) -> bool:
        self.refresh()
        return self._last_keep_resident

    def request_quit(self) -> None:
        self._quit_requested = True
        self._last_keep_resident = False
        if self._tray_icon is not None:
            self._tray_icon.hide()
        self._set_quit_on_last_window_closed(True)
        if self._application is not None:
            self._application.quit()

    def _set_quit_on_last_window_closed(self, enabled: bool) -> None:
        if self._application is not None:
            self._application.setQuitOnLastWindowClosed(enabled)

    def _handle_activated(
        self,
        reason: QSystemTrayIcon.ActivationReason,
        open_callback: Callable[[], None],
    ) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            open_callback()
