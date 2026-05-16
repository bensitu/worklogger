"""Thin Qt shell window that composes Phase F presentation components."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import date
from typing import Protocol

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from worklogger.domain.shared.errors import AppError
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.settings import SettingsWorkflow
from worklogger.presentation.shell.residency import QtResidencyController
from worklogger.presentation.theme import ThemeEngine
from worklogger.presentation.viewmodels import (
    CalendarDisplayOptions,
    CalendarViewModel,
    StatsPanelViewModel,
    WorkLogEntryViewModel,
)
from worklogger.presentation.widgets import (
    CalendarView,
    StatsPanel,
    WorkLogEntryDraft,
    WorkLogEntryPanel,
)


class NotesWorkflow(Protocol):
    def open(self, day: date, parent: QWidget | None = None) -> object:
        ...


class QuickLogsWorkflow(Protocol):
    def open(self, day: date, parent: QWidget | None = None) -> object:
        ...


class AnalyticsWorkflow(Protocol):
    def open(self, day: date, parent: QWidget | None = None) -> object:
        ...


class AiAssistWorkflow(Protocol):
    def open(self, day: date, parent: QWidget | None = None) -> object:
        ...


class ReportsWorkflow(Protocol):
    def open(self, day: date, parent: QWidget | None = None) -> object:
        ...


@dataclass(frozen=True)
class AppWindowConfig:
    selected_day: date | None = None
    today: date | None = None
    theme: str = "blue"
    dark: bool = False
    custom_color: str | None = None
    standard_work_hours: float = 8.0
    monthly_target_hours: float = 168.0
    calendar_options: CalendarDisplayOptions = CalendarDisplayOptions()
    holidays: Mapping[date, str] | None = None
    account_name: str | None = None
    confirm_discard_changes: Callable[[], bool] | None = None


class AppWindow(QMainWindow):
    logout_requested = Signal()

    def __init__(
        self,
        *,
        calendar_view_model: CalendarViewModel,
        worklog_entry_view_model: WorkLogEntryViewModel,
        stats_panel_view_model: StatsPanelViewModel,
        config: AppWindowConfig | None = None,
        settings_workflow: SettingsWorkflow | None = None,
        quick_logs_workflow: QuickLogsWorkflow | None = None,
        analytics_workflow: AnalyticsWorkflow | None = None,
        ai_assist_workflow: AiAssistWorkflow | None = None,
        notes_workflow: NotesWorkflow | None = None,
        reports_workflow: ReportsWorkflow | None = None,
        residency_controller: QtResidencyController | None = None,
        theme_engine: ThemeEngine | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._calendar_view_model = calendar_view_model
        self._worklog_entry_view_model = worklog_entry_view_model
        self._stats_panel_view_model = stats_panel_view_model
        self._config = config or AppWindowConfig()
        self._settings_workflow = settings_workflow
        self._quick_logs_workflow = quick_logs_workflow
        self._analytics_workflow = analytics_workflow
        self._ai_assist_workflow = ai_assist_workflow
        self._notes_workflow = notes_workflow
        self._reports_workflow = reports_workflow
        self._residency_controller = residency_controller
        self._theme_engine = theme_engine or ThemeEngine()
        self._today = self._config.today or date.today()
        self._selected_day = self._config.selected_day or self._today
        self._current_month = self._selected_day.replace(day=1)
        self._holidays = dict(self._config.holidays or {})
        self._last_error: AppError | None = None
        self._entry_dirty = False

        self.setObjectName("app_window")
        self.setWindowTitle(_("WorkLogger"))
        self._build_ui()
        self._connect_signals()
        self.apply_theme()
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
    def current_month(self) -> date:
        return self._current_month

    @property
    def last_error(self) -> AppError | None:
        return self._last_error

    @property
    def has_unsaved_changes(self) -> bool:
        return self._entry_dirty

    def apply_theme(self) -> None:
        application = QApplication.instance()
        if application is None:
            return
        application.setPalette(
            self._theme_engine.qt_palette(
                self._config.theme,
                dark=self._config.dark,
                custom_color=self._config.custom_color,
            )
        )
        application.setStyleSheet(
            self._theme_engine.application_stylesheet(
                self._config.theme,
                dark=self._config.dark,
                custom_color=self._config.custom_color,
            )
        )

    def refresh(self) -> bool:
        self._last_error = None
        calendar_ok = self._refresh_calendar()
        entry_ok = self._refresh_entry()
        stats_ok = self._refresh_stats()
        if calendar_ok and entry_ok and stats_ok:
            self._set_status(_("Ready"))
            return True
        return False

    def select_day(self, day: date) -> bool:
        if day != self._selected_day and not self._confirm_discard_changes_if_needed():
            return False
        self._selected_day = day
        self._current_month = day.replace(day=1)
        return self.refresh()

    def previous_month(self) -> bool:
        if not self._confirm_discard_changes_if_needed():
            return False
        self._current_month = _add_months(self._current_month, -1)
        return self.refresh()

    def next_month(self) -> bool:
        if not self._confirm_discard_changes_if_needed():
            return False
        self._current_month = _add_months(self._current_month, 1)
        return self.refresh()

    def go_today(self) -> bool:
        if self._today != self._selected_day and not self._confirm_discard_changes_if_needed():
            return False
        self._selected_day = self._today
        self._current_month = self._today.replace(day=1)
        return self.refresh()

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("app_window_central_widget")
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)
        self.setCentralWidget(central)

        nav = QHBoxLayout()
        self.previous_month_button = QPushButton("<<")
        self.previous_month_button.setObjectName("previous_month_button")
        self.previous_month_button.setToolTip(_("Previous month"))
        self.today_button = QPushButton(_("Today"))
        self.today_button.setObjectName("today_button")
        self.next_month_button = QPushButton(">>")
        self.next_month_button.setObjectName("next_month_button")
        self.next_month_button.setToolTip(_("Next month"))
        self.account_label = QLabel(self._account_text())
        self.account_label.setObjectName("account_label")
        self.quick_logs_button = QPushButton(_("Quick Log"))
        self.quick_logs_button.setObjectName("quick_logs_button")
        self.quick_logs_button.setToolTip(_("Quick Log"))
        self.notes_button = QPushButton(_("Notes"))
        self.notes_button.setObjectName("notes_button")
        self.notes_button.setToolTip(_("Notes"))
        self.reports_button = QPushButton(_("Reports"))
        self.reports_button.setObjectName("reports_button")
        self.reports_button.setToolTip(_("Reports"))
        self.analytics_button = QPushButton(_("Analytics"))
        self.analytics_button.setObjectName("analytics_button")
        self.analytics_button.setToolTip(_("Analytics"))
        self.ai_assist_button = QPushButton(_("AI Assist"))
        self.ai_assist_button.setObjectName("ai_assist_button")
        self.ai_assist_button.setToolTip(_("AI Assist"))
        self.settings_button = QPushButton(_("Settings"))
        self.settings_button.setObjectName("settings_button")
        self.settings_button.setToolTip(_("Settings"))
        self.logout_button = QPushButton(_("Logout"))
        self.logout_button.setObjectName("logout_button")
        self.logout_button.setToolTip(_("Logout"))
        self.status_label = QLabel("")
        self.status_label.setObjectName("app_status_label")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        nav.addWidget(self.previous_month_button)
        nav.addWidget(self.today_button)
        nav.addWidget(self.next_month_button)
        nav.addStretch(1)
        if self._config.account_name:
            nav.addWidget(self.account_label)
            nav.addWidget(self.quick_logs_button)
            nav.addWidget(self.notes_button)
            nav.addWidget(self.reports_button)
            nav.addWidget(self.analytics_button)
            nav.addWidget(self.ai_assist_button)
            nav.addWidget(self.settings_button)
            nav.addWidget(self.logout_button)
        else:
            self.account_label.setVisible(False)
            self.quick_logs_button.setVisible(False)
            self.notes_button.setVisible(False)
            self.reports_button.setVisible(False)
            self.analytics_button.setVisible(False)
            self.ai_assist_button.setVisible(False)
            self.settings_button.setVisible(False)
            self.logout_button.setVisible(False)
        if self._quick_logs_workflow is None:
            self.quick_logs_button.setVisible(False)
        if self._notes_workflow is None:
            self.notes_button.setVisible(False)
        if self._reports_workflow is None:
            self.reports_button.setVisible(False)
        if self._analytics_workflow is None:
            self.analytics_button.setVisible(False)
        if self._ai_assist_workflow is None:
            self.ai_assist_button.setVisible(False)
        if self._settings_workflow is None:
            self.settings_button.setVisible(False)
        nav.addWidget(self.status_label)
        root.addLayout(nav)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("main_splitter")
        root.addWidget(splitter, 1)

        self.calendar_view = CalendarView()
        splitter.addWidget(self.calendar_view)

        right = QWidget()
        right.setObjectName("right_panel_widget")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(10, 0, 0, 0)
        right_layout.setSpacing(10)
        self.stats_panel = StatsPanel()
        self.entry_panel = WorkLogEntryPanel()
        right_layout.addWidget(self.stats_panel)
        right_layout.addWidget(self.entry_panel, 1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

    def _connect_signals(self) -> None:
        self.previous_month_button.clicked.connect(self.previous_month)
        self.today_button.clicked.connect(self.go_today)
        self.next_month_button.clicked.connect(self.next_month)
        self.quick_logs_button.clicked.connect(self.open_quick_logs)
        self.notes_button.clicked.connect(self.open_notes)
        self.reports_button.clicked.connect(self.open_reports)
        self.analytics_button.clicked.connect(self.open_analytics)
        self.ai_assist_button.clicked.connect(self.open_ai_assist)
        self.settings_button.clicked.connect(self.open_settings)
        self.logout_button.clicked.connect(self._request_logout)
        self.calendar_view.day_selected.connect(self.select_day)
        self.entry_panel.draft_changed.connect(self._preview_entry_draft)
        self.entry_panel.save_requested.connect(self._save_entry_draft)

    def _refresh_calendar(self) -> bool:
        options = replace(
            self._config.calendar_options,
            standard_work_hours=float(self._config.standard_work_hours),
        )
        result = self._calendar_view_model.build_month(
            year=self._current_month.year,
            month=self._current_month.month,
            selected_day=self._selected_day,
            today=self._today,
            holidays=self._holidays,
            options=options,
            theme=self._config.theme,
            dark=self._config.dark,
            custom_color=self._config.custom_color,
        )
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return False
        self.calendar_view.set_state(result.value)
        return True

    def _refresh_entry(self) -> bool:
        result = self._worklog_entry_view_model.load(
            self._selected_day,
            holiday_note=self._holiday_note_for_selected_day(),
        )
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return False
        self.entry_panel.set_form(result.value)
        self._entry_dirty = result.value.dirty
        return True

    def _refresh_stats(self) -> bool:
        result = self._stats_panel_view_model.build_month(
            year=self._current_month.year,
            month=self._current_month.month,
            standard_work_hours=self._config.standard_work_hours,
            monthly_target_hours=self._config.monthly_target_hours,
        )
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return False
        self.stats_panel.set_state(result.value)
        return True

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
        if result.value.errors:
            self._set_status(", ".join(result.value.errors))
        else:
            self._set_status(_("Ready"))

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
        self._refresh_calendar()
        self._refresh_stats()
        self._set_status(_("Saved"))

    def _holiday_note_for_selected_day(self) -> str:
        if not self._config.calendar_options.show_holidays:
            return ""
        return str(self._holidays.get(self._selected_day, "")).strip()

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
        self._settings_workflow.open(self)
        self.refresh()
        if self._residency_controller is not None:
            self._residency_controller.refresh()
        return True

    def open_notes(self) -> bool:
        if self._notes_workflow is None:
            return False
        self._notes_workflow.open(self._selected_day, self)
        self.refresh()
        return True

    def open_quick_logs(self) -> bool:
        if self._quick_logs_workflow is None:
            return False
        self._quick_logs_workflow.open(self._selected_day, self)
        self.refresh()
        return True

    def open_reports(self) -> bool:
        if self._reports_workflow is None:
            return False
        self._reports_workflow.open(self._selected_day, self)
        self.refresh()
        return True

    def open_analytics(self) -> bool:
        if self._analytics_workflow is None:
            return False
        self._analytics_workflow.open(self._selected_day, self)
        self.refresh()
        return True

    def open_ai_assist(self) -> bool:
        if self._ai_assist_workflow is None:
            return False
        self._ai_assist_workflow.open(self._selected_day, self)
        self.refresh()
        return True

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._confirm_discard_changes_if_needed():
            if hasattr(event, "ignore"):
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

    def _restore_from_residency(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit_from_residency(self) -> None:
        if self._residency_controller is not None:
            self._residency_controller.request_quit()
        self.close()

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


def _add_months(first_day: date, months: int) -> date:
    month_index = first_day.month - 1 + months
    year = first_day.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)
