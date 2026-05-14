"""Minimal work-log entry shell."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from worklogger.domain.shared.errors import AppError
from worklogger.infrastructure.i18n import _
from worklogger.presentation.settings import SettingsWorkflow
from worklogger.presentation.shell.residency import QtResidencyController
from worklogger.presentation.viewmodels import WorkLogEntryViewModel
from worklogger.presentation.widgets import WorkLogEntryDraft, WorkLogEntryPanel


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
        worklog_entry_view_model: WorkLogEntryViewModel,
        config: MinimalViewConfig | None = None,
        settings_workflow: SettingsWorkflow | None = None,
        residency_controller: QtResidencyController | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._worklog_entry_view_model = worklog_entry_view_model
        self._config = config or MinimalViewConfig()
        self._settings_workflow = settings_workflow
        self._residency_controller = residency_controller
        self._today = self._config.today or date.today()
        self._selected_day = self._config.selected_day or self._today
        self._entry_dirty = False
        self._last_error: AppError | None = None

        self.setObjectName("minimal_view")
        self.setWindowTitle(_("WorkLogger"))
        self._build_ui()
        self._connect_signals()
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
        result = self._worklog_entry_view_model.load(self._selected_day)
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return False
        self.entry_panel.set_form(result.value)
        self._entry_dirty = result.value.dirty
        self._set_status(_("Ready"))
        return True

    def previous_day(self) -> bool:
        return self.select_day(self._selected_day - timedelta(days=1))

    def next_day(self) -> bool:
        return self.select_day(self._selected_day + timedelta(days=1))

    def go_today(self) -> bool:
        return self.select_day(self._today)

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
        self.account_label.setObjectName("account_label")
        self.settings_button = QPushButton(_("Settings"))
        self.settings_button.setObjectName("nav_btn")
        self.settings_button.setToolTip(_("Settings"))
        self.logout_button = QPushButton(_("Logout"))
        self.logout_button.setObjectName("nav_btn")
        self.logout_button.setToolTip(_("Logout"))
        nav.addWidget(self.previous_button)
        nav.addWidget(self.today_button)
        nav.addWidget(self.next_button)
        nav.addWidget(self.date_label, 1)
        if self._config.account_name:
            nav.addWidget(self.account_label)
            nav.addWidget(self.settings_button)
            nav.addWidget(self.logout_button)
        else:
            self.settings_button.setVisible(False)
            self.logout_button.setVisible(False)
        if self._settings_workflow is None:
            self.settings_button.setVisible(False)
        root.addLayout(nav)

        self.entry_panel = WorkLogEntryPanel()
        root.addWidget(self.entry_panel)

        self.status_label = QLabel("")
        self.status_label.setObjectName("status_label")
        root.addWidget(self.status_label)

    def _connect_signals(self) -> None:
        self.previous_button.clicked.connect(self.previous_day)
        self.today_button.clicked.connect(self.go_today)
        self.next_button.clicked.connect(self.next_day)
        self.settings_button.clicked.connect(self.open_settings)
        self.logout_button.clicked.connect(self._request_logout)
        self.entry_panel.draft_changed.connect(self._preview_entry_draft)
        self.entry_panel.save_requested.connect(self._save_entry_draft)

    def _preview_entry_draft(self, draft: WorkLogEntryDraft) -> None:
        result = self._worklog_entry_view_model.preview(
            draft.day,
            start_time=draft.start_time,
            end_time=draft.end_time,
            break_hours=draft.break_hours,
            note=draft.note,
            work_type=draft.work_type,
        )
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return
        self.entry_panel.set_form(result.value)
        self._entry_dirty = result.value.dirty
        self._set_status(", ".join(result.value.errors) if result.value.errors else _("Ready"))

    def _save_entry_draft(self, draft: WorkLogEntryDraft) -> None:
        preview = self._worklog_entry_view_model.preview(
            draft.day,
            start_time=draft.start_time,
            end_time=draft.end_time,
            break_hours=draft.break_hours,
            note=draft.note,
            work_type=draft.work_type,
        )
        if not preview.ok or preview.value is None:
            self._set_error(preview.error)
            return
        if preview.value.errors:
            self.entry_panel.set_form(preview.value)
            self._set_status(", ".join(preview.value.errors))
            return
        saved = self._worklog_entry_view_model.save(preview.value)
        if not saved.ok or saved.value is None:
            self._set_error(saved.error)
            return
        self.entry_panel.set_form(saved.value)
        self._entry_dirty = saved.value.dirty
        self._set_status(_("Saved"))

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
        if not self._entry_dirty:
            return True
        if self._config.confirm_discard_changes is not None:
            confirmed = bool(self._config.confirm_discard_changes())
        else:
            confirmed = self._ask_discard_changes()
        if not confirmed:
            self._set_status(_("Unsaved changes"))
            return False
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
        self._set_status(error.message if error else _("Unknown error"))

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
        self._settings_workflow.open(self)
        self.refresh()
        if self._residency_controller is not None:
            self._residency_controller.refresh()
        return True

    def _restore_from_residency(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit_from_residency(self) -> None:
        if self._residency_controller is not None:
            self._residency_controller.request_quit()
        self.close()
