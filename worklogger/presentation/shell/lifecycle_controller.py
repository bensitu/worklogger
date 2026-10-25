"""Shared window residency, date polling, and presentation cleanup."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QWidget

if TYPE_CHECKING:
    from worklogger.presentation.shell.residency import QtResidencyController
    from worklogger.presentation.widgets.time_entries import TimeEntryPanel


class WindowLifecycleController(QObject):
    def __init__(self, window: QWidget, entry_panel: TimeEntryPanel, *, residency: QtResidencyController | None = None,
                 confirm_close: Callable[[], bool], update_today: Callable[[], None],
                 poll_dates: bool, close_callbacks: Iterable[Callable[[], None]] = ()):
        super().__init__(window)
        self._window, self._entries, self._residency = window, entry_panel, residency
        self._confirm_close, self._update_today = confirm_close, update_today
        self._poll_dates = poll_dates
        self._close_callbacks = tuple(close_callbacks)
        self._disposed = False
        self._date_timer = QTimer(self)
        self._date_timer.setInterval(60_000)
        self._date_timer.timeout.connect(update_today)
        if poll_dates:
            self._date_timer.start()
        window.installEventFilter(self)
        if residency is not None:
            residency.attach(window, open_callback=self.restore, quit_callback=self.request_quit)
            if hasattr(residency, "notify_timer_reminder"):
                entry_panel.reminder.connect(residency.notify_timer_reminder)
            if hasattr(residency, "bind_recording"):
                residency.bind_recording(start_callback=entry_panel.start_recording,
                    end_callback=entry_panel.end_recording, state_probe=entry_panel.recording_action_state)
                entry_panel.recording_changed.connect(residency.update_recording_actions)
                entry_panel.busy_changed.connect(lambda _busy: residency.update_recording_actions())

    def eventFilter(self, watched, event):
        if watched is self._window and not self._disposed:
            if event.type() == QEvent.Type.Hide:
                self._date_timer.stop()
            elif event.type() == QEvent.Type.Show and self._poll_dates:
                self._date_timer.start()
                self._update_today()
            elif (event.type() == QEvent.Type.WindowStateChange and self._window.isMinimized()
                    and self._residency is not None and self._residency.should_hide_on_minimize()):
                self._window.hide()
        return False

    def restore(self) -> None:
        self._window.showNormal()
        self._window.raise_()
        self._window.activateWindow()

    def request_quit(self) -> None:
        if not self._confirm_close():
            return
        if self._residency is not None:
            self._residency.request_quit()
        self._window.close()

    def prepare_close(self) -> bool:
        if self._disposed:
            return True
        if not self._confirm_close():
            return False
        if (self._residency is not None and not self._residency.quit_requested
                and self._residency.should_hide_on_close()):
            self._date_timer.stop()
            self._window.hide()
            return False
        self._disposed = True
        self._date_timer.stop()
        self._entries.auto_timer.stop()
        for callback in self._close_callbacks:
            callback()
        return True
