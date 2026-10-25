"""Tray and menu-bar residency presentation state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import sys
from typing import Protocol

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon, QWidget
from shiboken6 import isValid

from worklogger.app.commands.settings_commands import SetSettingCommand
from worklogger.app.queries.settings_queries import GetSettingQuery
from worklogger.app.settings import read_setting_values
from worklogger.config.constants import (
    WINDOW_CLOSE_ACTION_SETTING_KEY,
    MINIMIZE_TO_TRAY_SETTING_KEY,
)
from worklogger.domain.settings.preferences import SETTINGS_DEFAULTS
from worklogger.domain.settings.values import setting_bool
from worklogger.domain.settings.window_behavior import WindowCloseAction
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import _
from worklogger.presentation.platform_integration import residency_setting_key


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
    close_action: WindowCloseAction = WindowCloseAction.HIDE
    minimize_to_tray: bool = True

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
        loaded = read_setting_values(self._get_handler, self._user_id,
            {name: SETTINGS_DEFAULTS[name] for name in (key, WINDOW_CLOSE_ACTION_SETTING_KEY, MINIMIZE_TO_TRAY_SETTING_KEY)})
        if not loaded.ok:
            return Result.failure(loaded.error or _error("residency_load_failed"))
        values = loaded.value
        return Result.success(
            ResidencyState(
                platform=self._platform,
                setting_key=key,
                available=available,
                enabled=available and setting_bool(values[key]),
                close_action=WindowCloseAction.from_setting(values[WINDOW_CLOSE_ACTION_SETTING_KEY]),
                minimize_to_tray=setting_bool(values[MINIMIZE_TO_TRAY_SETTING_KEY], True),
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
        self._start_action = None
        self._end_action = None
        self._start_recording = None
        self._end_recording = None
        self._recording_state = None
        self._close_action = WindowCloseAction.EXIT
        self._minimize_to_tray = False
        self._window = None
        self._open_callback = None
        self._quit_callback = None
        self._availability_timer = None

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
        self._window = parent
        self._open_callback = open_callback or parent.show
        self._quit_callback = quit_callback or self.request_quit
        self._availability_timer = QTimer(parent)
        self._availability_timer.setInterval(5_000)
        self._availability_timer.timeout.connect(self.should_keep_resident)
        self.refresh()

    def _ensure_tray_icon(self) -> None:
        parent = self._window
        if parent is None or not isValid(parent):
            return
        if self._tray_icon is None and self._tray_available():
            icon = parent.windowIcon()
            if icon.isNull():
                icon = parent.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
            self._tray_icon = QSystemTrayIcon(icon, parent)
            menu = QMenu(parent)
            open_action = QAction(_("Open"), parent)
            open_action.triggered.connect(self._open_callback)
            quit_action = QAction(_("Quit"), parent)
            quit_action.triggered.connect(self._quit_callback)
            menu.addAction(open_action)
            menu.addSeparator()
            self._start_action = menu.addAction(_("Start recording"))
            self._end_action = menu.addAction(_("End recording"))
            self._start_action.triggered.connect(lambda: self._run_recording_action(True))
            self._end_action.triggered.connect(lambda: self._run_recording_action(False))
            menu.addSeparator()
            menu.addAction(quit_action)
            menu.aboutToShow.connect(self.update_recording_actions)
            self._tray_icon.setContextMenu(menu)
            self._tray_icon.activated.connect(
                lambda reason: self._handle_activated(reason, self._open_callback)
            )

    def bind_recording(self, *, start_callback, end_callback, state_probe):
        self._start_recording = start_callback
        self._end_recording = end_callback
        self._recording_state = state_probe
        self.update_recording_actions()

    def update_recording_actions(self):
        if self._start_action is None:
            return
        supported = self._recording_state is not None
        self._start_action.setVisible(supported)
        self._end_action.setVisible(supported)
        can_start, can_end = self._recording_state() if supported else (False, False)
        self._start_action.setEnabled(can_start and not self._quit_requested)
        self._end_action.setEnabled(can_end and not self._quit_requested)

    def _run_recording_action(self, start):
        self.update_recording_actions()
        action = self._start_action if start else self._end_action
        callback = self._start_recording if start else self._end_recording
        if action is not None and action.isEnabled() and callback is not None:
            callback()
        self.update_recording_actions()

    def refresh(self) -> ResidencyState | None:
        was_resident = self._last_keep_resident
        self.update_recording_actions()
        state = self._view_model.load()
        if not state.ok or state.value is None:
            self._last_keep_resident = False
            self._set_quit_on_last_window_closed(True)
            if was_resident:
                self._restore_hidden_window()
            return None
        self._close_action = state.value.close_action
        self._minimize_to_tray = state.value.minimize_to_tray
        self._ensure_tray_icon()
        self._last_keep_resident = bool(
            state.value.keep_resident and self._tray_available()
        )
        self._set_quit_on_last_window_closed(not self.should_hide_on_close())
        if self._availability_timer is not None:
            if self._last_keep_resident:
                self._availability_timer.start()
            else:
                self._availability_timer.stop()
        if was_resident and not self._last_keep_resident:
            self._restore_hidden_window()
        if self._tray_icon is not None:
            self._tray_icon.setToolTip(_("WorkLogger"))
            if self._last_keep_resident:
                self._tray_icon.show()
            else:
                self._tray_icon.hide()
        return state.value

    def should_keep_resident(self) -> bool:
        if self._last_keep_resident and not self._tray_available():
            self._last_keep_resident = False
            self._set_quit_on_last_window_closed(True)
            if self._availability_timer is not None:
                self._availability_timer.stop()
            self._restore_hidden_window()
        return self._last_keep_resident

    def should_hide_on_close(self) -> bool:
        return self.should_keep_resident() and self._close_action == WindowCloseAction.HIDE

    def should_hide_on_minimize(self) -> bool:
        return self.should_keep_resident() and self._minimize_to_tray

    def _restore_hidden_window(self) -> None:
        if (not self._quit_requested and self._window is not None and isValid(self._window)
                and self._window.isHidden() and self._open_callback is not None):
            self._open_callback()

    def request_quit(self) -> None:
        self._quit_requested = True
        self._last_keep_resident = False
        if self._availability_timer is not None:
            self._availability_timer.stop()
        if self._tray_icon is not None:
            self._tray_icon.hide()
        self._set_quit_on_last_window_closed(True)
        if self._application is not None:
            self._application.quit()

    def notify_timer_reminder(self, message):
        self.notify_message(_("Timer reminder"), message)

    def notify_message(self, title, message, *, warning=False):
        if self._tray_icon is not None and self._last_keep_resident and self._tray_icon.isVisible():
            icon = QSystemTrayIcon.MessageIcon.Warning if warning else QSystemTrayIcon.MessageIcon.Information
            self._tray_icon.showMessage(title, message, icon, 10000)
            return True
        return False

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
