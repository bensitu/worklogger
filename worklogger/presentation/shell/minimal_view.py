"""Minimal work-log entry shell."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from PySide6.QtCore import QEvent, QTimer, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from worklogger.domain.shared.errors import AppError
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.settings import SettingsWorkflow
from worklogger.presentation.shell.residency import QtResidencyController
from worklogger.presentation.viewmodels.time_entries import TimeEntryViewModel
from worklogger.presentation.widgets.assets import apply_window_icon
from worklogger.presentation.widgets.status_label import StatusLabel
from worklogger.presentation.widgets.time_entries import TimeEntryPanel
from worklogger.presentation.widgets.time_entry_history import TimeEntryHistory


@dataclass(frozen=True)
class MinimalViewConfig:
    selected_day: date | None = None
    today: date | None = None
    account_name: str | None = None
    confirm_discard_changes: Callable[[], bool] | None = None


class MinimalView(QWidget):
    logout_requested = Signal()

    def __init__(
        self,
        *,
        time_entry_view_model: TimeEntryViewModel,
        config: MinimalViewConfig | None = None,
        settings_workflow: SettingsWorkflow | None = None,
        notes_workflow=None,
        residency_controller: QtResidencyController | None = None,
        job_runner=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._time_entry_view_model = time_entry_view_model
        self._config = config or MinimalViewConfig()
        self._settings_workflow = settings_workflow
        self._notes_workflow = notes_workflow
        self._residency_controller = residency_controller
        self._job_runner = job_runner
        self._today = self._config.today or date.today()
        timer = time_entry_view_model.timer
        restored_day = timer.started_at.date() if timer else None
        self._selected_day = self._config.selected_day or restored_day or self._today
        self._entry_dirty = False
        self._last_error: AppError | None = None

        self.setObjectName("minimal_view")
        self.setWindowTitle(_("WorkLogger"))
        apply_window_icon(self)
        self._build_ui()
        self._connect_signals()
        self._date_timer = QTimer(self)
        self._date_timer.setInterval(60_000)
        self._date_timer.timeout.connect(self._update_today)
        if self._config.today is None:
            self._date_timer.start()
        if self._residency_controller is not None:
            self._residency_controller.attach(
                self,
                open_callback=self._restore_from_residency,
                quit_callback=self._quit_from_residency,
            )

    @property
    def selected_day(self) -> date:
        return self._selected_day

    @property
    def has_unsaved_changes(self) -> bool:
        return self._entry_dirty

    @property
    def last_error(self) -> AppError | None:
        return self._last_error

    def refresh(self) -> bool:
        self._last_error = None
        self.date_label.setText(self._selected_day.isoformat())
        self.account_label.setText(self._account_text())
        result = self.entry_panel.load_day(self._selected_day)
        self._entry_dirty = self.entry_panel.is_dirty
        if not result.ok:
            self._set_error(result.error)
        else:
            self.history_widget.set_entries(result.value)
        return result.ok

    def previous_day(self) -> bool:
        return self.select_day(self._selected_day - timedelta(days=1))

    def next_day(self) -> bool:
        return self.select_day(self._selected_day + timedelta(days=1))

    def go_today(self) -> bool:
        self._update_today()
        return self.select_day(self._today)

    def _update_today(self) -> None:
        self._today = self._config.today or date.today()

    def select_day(self, day: date) -> bool:
        if day != self._selected_day and not self._confirm_discard_changes_if_needed():
            return False
        self._selected_day = day
        return self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        nav = QHBoxLayout()
        self.previous_button = QPushButton("<")
        self.previous_button.setToolTip(_("Previous day"))
        self.today_button = QPushButton(_("Today"))
        self.next_button = QPushButton(">")
        self.next_button.setToolTip(_("Next day"))
        self.date_label = QLabel("")
        self.date_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.account_label = QLabel("")
        self.account_label.setObjectName("minimal_account_label")
        self.settings_button = QPushButton(_("Settings"))
        self.settings_button.setObjectName("minimal_settings_button")
        self.settings_button.setToolTip(_("Settings"))
        nav.addWidget(self.previous_button)
        nav.addWidget(self.today_button)
        nav.addWidget(self.next_button)
        nav.addWidget(self.date_label, 1)
        self.notes_button = QPushButton(_("Daily notes"))
        self.notes_button.setVisible(self._notes_workflow is not None)
        nav.addWidget(self.notes_button)
        if self._config.account_name:
            nav.addWidget(self.account_label)
            nav.addWidget(self.settings_button)
        else:
            self.settings_button.setVisible(False)
        if self._settings_workflow is None:
            self.settings_button.setVisible(False)
        root.addLayout(nav)

        self.entry_panel = TimeEntryPanel(self._time_entry_view_model, compact=False, job_runner=self._job_runner)
        root.addWidget(self.entry_panel)
        root.addWidget(QLabel(_("Schedule / Records")))
        self.history_widget = TimeEntryHistory(self._time_entry_view_model)
        self.records_scroll = QScrollArea()
        self.records_scroll.setWidgetResizable(True)
        self.records_scroll.setMinimumHeight(120)
        self.records_scroll.setWidget(self.history_widget)
        root.addWidget(self.records_scroll, 1)

        self.status_label = StatusLabel()
        self.status_label.setObjectName("minimal_status_label")
        root.addWidget(self.status_label)

    def _connect_signals(self) -> None:
        self.previous_button.clicked.connect(self.previous_day)
        self.today_button.clicked.connect(self.go_today)
        self.next_button.clicked.connect(self.next_day)
        self.settings_button.clicked.connect(self.open_settings)
        self.notes_button.clicked.connect(self.open_notes)
        self.entry_panel.records_changed.connect(self._entries_changed)
        self.entry_panel.dirty_changed.connect(lambda dirty: setattr(self, "_entry_dirty", dirty))
        self.entry_panel.selection_changed.connect(self.history_widget.set_selected_entry)
        self.history_widget.entry_selected.connect(self.entry_panel.edit_entry)
        self.history_widget.entry_delete_requested.connect(self.entry_panel.delete_entry)
        self.entry_panel.busy_changed.connect(self.history_widget.setDisabled)

    def _entries_changed(self, day: date):
        if self.entry_panel.time_tabs.currentIndex() == 1:
            self._selected_day = day
        self.refresh()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._confirm_discard_changes_if_needed():
            event.ignore()
            return
        if (
            self._residency_controller is not None
            and not self._residency_controller.quit_requested
            and self._residency_controller.should_keep_resident()
        ):
            self.hide()
            event.ignore()
            return
        if isinstance(self.entry_panel, TimeEntryPanel):
            self.entry_panel.auto_timer.stop()
        super().closeEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if (
            event.type() == QEvent.Type.WindowStateChange
            and self.isMinimized()
            and self._residency_controller is not None
            and self._residency_controller.should_keep_resident()
        ):
            self.hide()

    def _confirm_discard_changes_if_needed(self) -> bool:
        if bool(getattr(self._notes_workflow, "is_open", False)):
            return False
        if isinstance(self.entry_panel, TimeEntryPanel) and self.entry_panel.is_busy:
            self._set_status(_("Please wait for the current operation."))
            return False
        if not self._entry_dirty:
            return True
        if self._config.confirm_discard_changes is not None:
            confirmed = bool(self._config.confirm_discard_changes())
        else:
            confirmed = self._ask_discard_changes()
        if not confirmed:
            self._set_status(_("Unsaved changes"))
            return False
        if isinstance(self.entry_panel, TimeEntryPanel):
            self.entry_panel.discard_changes()
        self._entry_dirty = False
        return True

    def _ask_discard_changes(self) -> bool:
        answer = QMessageBox.question(
            self,
            _("Discard changes?"),
            _("You have unsaved work log changes. Discard them?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _set_error(self, error: AppError | None) -> None:
        self._last_error = error
        self._set_status(display_error_message(error))

    def _set_status(self, message: str) -> None:
        self.status_label.setText(message)

    def _account_text(self) -> str:
        account_name = str(self._config.account_name or "").strip()
        return _("Signed in: {username}").format(username=account_name) if account_name else ""

    def _request_logout(self) -> None:
        if not self._confirm_discard_changes_if_needed():
            return
        self._set_status(_("Logout requested"))
        self.logout_requested.emit()

    def open_settings(self) -> bool:
        if self._settings_workflow is None:
            return False
        logged_out = False
        if hasattr(self._settings_workflow, "create_dialog"):
            dialog = self._settings_workflow.create_dialog(self)

            def logout() -> None:
                nonlocal logged_out
                if self._confirm_discard_changes_if_needed():
                    logged_out = True
                    dialog.accept()
                    self._set_status(_("Logout requested"))
                    self.logout_requested.emit()

            dialog.logout_requested.connect(logout)
            try:
                dialog.exec()
            finally:
                dialog.logout_requested.disconnect(logout)
                dialog.deleteLater()
        else:
            self._settings_workflow.open(self)
        if logged_out:
            return True
        self.refresh()
        if self._residency_controller is not None:
            self._residency_controller.refresh()
        return True

    def open_notes(self) -> bool:
        if self._notes_workflow is None or self.entry_panel.is_busy:
            return False
        self._notes_workflow.open(self._selected_day, self)
        self.refresh()
        return True

    def _restore_from_residency(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit_from_residency(self) -> None:
        if self._residency_controller is not None:
            self._residency_controller.request_quit()
        self.close()
