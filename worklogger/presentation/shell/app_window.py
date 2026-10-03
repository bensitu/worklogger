"""Qt application window composing navigation and presentation workflows."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import date
from typing import Protocol
from worklogger.app.job_runner import JobRunner

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QMenu,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from worklogger.domain.shared.errors import AppError
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.date_labels import month_label
from worklogger.presentation.settings import SettingsWorkflow
from worklogger.presentation.shell.pages import (
    AnalyticsPage,
    CalendarPage,
    ReportsPage,
    UnavailableSettingsPage,
)
from worklogger.presentation.shell.residency import QtResidencyController
from worklogger.presentation.theme import ThemeEngine, install_bundled_fonts
from worklogger.presentation.viewmodels import (
    CalendarDisplayOptions,
    CalendarViewModel,
    StatsPanelViewModel,
    WorkLogEntryViewModel,
    SettingsState,
)
from worklogger.presentation.widgets import (
    CalendarView,
    SidebarWidget,
    StatsPanel,
    WorkLogEntryDraft,
    WorkLogEntryPanel,
)
from worklogger.presentation.widgets.assets import apply_window_icon


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
    account_role: str = "Admin"
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
        job_runner: JobRunner | None = None,
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
        reports_model = getattr(reports_workflow, "view_model", None)
        if hasattr(reports_model, "set_standard_work_hours"):
            reports_model.set_standard_work_hours(self._config.standard_work_hours)
        self._residency_controller = residency_controller
        self._theme_engine = theme_engine or ThemeEngine()
        self._job_runner = job_runner
        self._today = self._config.today or date.today()
        self._selected_day = self._config.selected_day or self._today
        self._current_month = self._selected_day.replace(day=1)
        # None requests regional holidays; an explicit mapping overrides the provider.
        self._holidays = None if self._config.holidays is None else dict(self._config.holidays)
        self._last_error: AppError | None = None
        self._refreshing = False
        self._entry_dirty = False

        self.setObjectName("app_window")
        self.setWindowTitle(_("WorkLogger"))
        apply_window_icon(self)
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
        return self._entry_dirty or self.reports_page.has_unsaved_changes

    def apply_theme(self) -> None:
        application = QApplication.instance()
        if application is None:
            return
        install_bundled_fonts()
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

    def apply_settings(self, state: SettingsState) -> None:
        self._config = replace(
            self._config, theme=state.theme, dark=state.dark_mode,
            custom_color=state.custom_color, standard_work_hours=state.standard_work_hours,
            monthly_target_hours=state.monthly_target_hours,
            calendar_options=replace(
                self._config.calendar_options, show_holidays=state.show_holidays,
                show_note_markers=state.show_note_markers,
                show_overnight_indicator=state.show_overnight_indicator,
                week_start_monday=state.week_start_monday,
            ),
        )
        self._worklog_entry_view_model.set_default_break_hours(state.default_break_hours)
        reports_model = getattr(self._reports_workflow, "view_model", None)
        if hasattr(reports_model, "set_standard_work_hours"):
            reports_model.set_standard_work_hours(state.standard_work_hours)
        self.apply_theme()
        self._refresh_calendar()
        self._refresh_stats()
        if not self._entry_dirty:
            self._refresh_entry()
        if self._residency_controller is not None:
            self._residency_controller.refresh()

    def refresh(self) -> bool:
        self._last_error = None
        self._refreshing = True
        try:
            calendar_ok = self._refresh_calendar()
            entry_ok = self._refresh_entry()
            stats_ok = self._refresh_stats()
        finally:
            self._refreshing = False
        if calendar_ok and entry_ok and stats_ok:
            self._set_status("")
            return True
        self._set_error(self._last_error)
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
        self.resize(1100, 700)
        self.setMinimumSize(880, 580)
        central = QWidget()
        central.setObjectName("app_window_central_widget")
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(central)

        self.sidebar = SidebarWidget(
            account_name=self._config.account_name or "",
            role=self._config.account_role,
        )
        root.addWidget(self.sidebar)

        main = QWidget()
        main.setObjectName("app_main_content_widget")
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        root.addWidget(main, 1)

        self.page_stack = QStackedWidget()
        self.page_stack.setObjectName("app_page_stack_widget")
        main_layout.addWidget(self.page_stack, 1)

        self.calendar_view = CalendarView()
        self.entry_panel = WorkLogEntryPanel(compact=True)
        self.stats_panel = StatsPanel()
        self.calendar_page = CalendarPage(
            calendar_view=self.calendar_view,
            entry_panel=self.entry_panel,
            stats_panel=self.stats_panel,
        )
        self.analytics_page = AnalyticsPage(
            getattr(self._analytics_workflow, "view_model", None),
            self._selected_day,
        )
        self.reports_page = ReportsPage(
            getattr(self._reports_workflow, "view_model", None),
            self._selected_day,
            job_runner=self._job_runner,
            confirm_discard=self._config.confirm_discard_changes,
        )
        if hasattr(self._settings_workflow, "create_page"):
            self.settings_page = self._settings_workflow.create_page(self)
        else:
            self.settings_page = UnavailableSettingsPage()

        self._page_routes = {
            "calendar": self.page_stack.addWidget(self.calendar_page),
            "analytics": self.page_stack.addWidget(self.analytics_page),
            "reports": self.page_stack.addWidget(self.reports_page),
            "settings": self.page_stack.addWidget(self.settings_page),
        }

        self.previous_month_button = self.calendar_page.previous_month_button
        self.today_button = self.calendar_page.today_button
        self.next_month_button = self.calendar_page.next_month_button
        self.account_label = QLabel(self._account_text())
        self.account_label.setObjectName("account_label")
        self.quick_logs_button = QPushButton(_("Quick Log"))
        self.quick_logs_button.setObjectName("quick_logs_button")
        self.quick_logs_button.setToolTip(_("Quick Log"))
        self.quick_logs_button.setProperty("variant", "ghost")
        self.notes_button = QPushButton(_("Notes"))
        self.notes_button.setObjectName("notes_button")
        self.notes_button.setToolTip(_("Notes"))
        self.notes_button.setProperty("variant", "ghost")
        self.reports_button = self.sidebar._buttons["reports"]
        self.analytics_button = self.sidebar._buttons["analytics"]
        self.ai_assist_button = QPushButton(_("AI Assist"))
        self.ai_assist_button.setObjectName("ai_assist_button")
        self.ai_assist_button.setToolTip(_("AI Assist"))
        self.ai_assist_button.setProperty("variant", "ghost")
        self.settings_button = self.sidebar.settings_button
        self.status_label = QLabel("")
        self.status_label.setObjectName("app_status_label")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.status_label.hide()

        actions = QMenu(self)
        for button, workflow in (
            (self.quick_logs_button, self._quick_logs_workflow),
            (self.notes_button, self._notes_workflow),
            (self.ai_assist_button, self._ai_assist_workflow),
        ):
            button.hide()
            if workflow is not None:
                actions.addAction(button.text(), button.click)
        self.calendar_page.add_entry_button.setMenu(actions)
        self.calendar_page.add_entry_button.setEnabled(not actions.isEmpty())
        self.account_label.setVisible(False)
        if self._quick_logs_workflow is None:
            self.quick_logs_button.setVisible(False)
        if self._notes_workflow is None:
            self.notes_button.setVisible(False)
        if self._ai_assist_workflow is None:
            self.ai_assist_button.setVisible(False)
        main_layout.addWidget(self.status_label)

    def _connect_signals(self) -> None:
        self.sidebar.route_changed.connect(self._switch_route)
        self.calendar_page.previous_month_requested.connect(self.previous_month)
        self.calendar_page.today_requested.connect(self.go_today)
        self.calendar_page.next_month_requested.connect(self.next_month)
        self.quick_logs_button.clicked.connect(self.open_quick_logs)
        self.notes_button.clicked.connect(self.open_notes)
        self.ai_assist_button.clicked.connect(self.open_ai_assist)
        if hasattr(self.settings_page, "logout_requested"):
            self.settings_page.logout_requested.connect(self._request_logout)
        if hasattr(self.settings_page, "settings_changed"):
            self.settings_page.settings_changed.connect(self.apply_settings)
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
        self.calendar_page.set_month_title(
            month_label(date(result.value.year, result.value.month, 1))
        )
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
        events = self._calendar_view_model.events_for_day(self._selected_day)
        if not events.ok:
            self._set_error(events.error)
            return False
        summary = _record_summary(result.value)
        lines = ["\n".join(summary)] if summary else []
        for event in sorted(events.value or (), key=lambda value: (value.start_time or "", value.summary)):
            time_text = _("All day") if event.all_day else f"{event.start_time or '--:--'} - {event.end_time or '--:--'}"
            lines.append(f"{time_text}\n{event.summary}")
        self.calendar_page.set_record_summary(tuple(lines))
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
        self.entry_panel.set_preview_form(result.value)
        self._entry_dirty = result.value.dirty
        if result.value.errors:
            self._set_status(", ".join(result.value.errors))
        else:
            self._set_status("")

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
            self.entry_panel.set_preview_form(preview.value)
            self._set_status(", ".join(preview.value.errors), notify=True, error=True)
            return
        saved = self._worklog_entry_view_model.save(preview.value)
        if not saved.ok or saved.value is None:
            self._set_error(saved.error)
            return
        self.entry_panel.set_form(saved.value)
        self._entry_dirty = saved.value.dirty
        self._refresh_entry()
        self._refresh_calendar()
        self._refresh_stats()
        self._set_status(_("Saved"))

    def _holiday_note_for_selected_day(self) -> str:
        if not self._config.calendar_options.show_holidays:
            return ""
        state = self.calendar_view.state
        if state is not None:
            for cell in state.cells:
                if cell.day == self._selected_day:
                    return cell.holiday_name
        return str((self._holidays or {}).get(self._selected_day, "")).strip()

    def _set_error(self, error: AppError | None) -> None:
        self._last_error = error
        self._set_status(display_error_message(error), notify=not self._refreshing, error=True)

    def _set_status(self, message: str, *, notify: bool = False, error: bool = False) -> None:
        self.status_label.setText(message)
        self.status_label.hide()
        if message and notify:
            show = QMessageBox.warning if error else QMessageBox.information
            show(self, _("WorkLogger"), message)

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
        if hasattr(self._settings_workflow, "create_page"):
            return self._switch_route("settings")
        if not self._confirm_discard_changes_if_needed():
            return False
        self._settings_workflow.open(self)
        self.refresh()
        if self._residency_controller is not None:
            self._residency_controller.refresh()
        return True

    def open_notes(self) -> bool:
        if self._notes_workflow is None:
            return False
        if not self._confirm_discard_changes_if_needed():
            return False
        self._notes_workflow.open(self._selected_day, self)
        self.refresh()
        return True

    def open_quick_logs(self) -> bool:
        if self._quick_logs_workflow is None:
            return False
        if not self._confirm_discard_changes_if_needed():
            return False
        self._quick_logs_workflow.open(self._selected_day, self)
        self.refresh()
        return True

    def open_reports(self) -> bool:
        if self._reports_workflow is None:
            return False
        if getattr(self._reports_workflow, "view_model", None) is not None:
            return self._switch_route("reports")
        if not self._confirm_discard_changes_if_needed():
            return False
        self._reports_workflow.open(self._selected_day, self)
        self.refresh()
        return True

    def open_analytics(self) -> bool:
        if self._analytics_workflow is None:
            return False
        if getattr(self._analytics_workflow, "view_model", None) is not None:
            return self._switch_route("analytics")
        if not self._confirm_discard_changes_if_needed():
            return False
        self._analytics_workflow.open(self._selected_day, self)
        self.refresh()
        return True

    def open_ai_assist(self) -> bool:
        if self._ai_assist_workflow is None:
            return False
        if not self._confirm_discard_changes_if_needed():
            return False
        self._ai_assist_workflow.open(self._selected_day, self)
        self.refresh()
        return True

    def _switch_route(self, route: str) -> bool:
        normalized = str(route or "calendar").strip().lower()
        if normalized == "analytics" and getattr(self._analytics_workflow, "view_model", None) is None:
            opened = self.open_analytics()
            self.sidebar.set_active_route("calendar")
            return opened
        if normalized == "reports" and getattr(self._reports_workflow, "view_model", None) is None:
            opened = self.open_reports()
            self.sidebar.set_active_route("calendar")
            return opened
        if normalized == "settings" and not hasattr(self._settings_workflow, "create_page"):
            opened = self.open_settings()
            self.sidebar.set_active_route("calendar")
            return opened
        if not self._confirm_discard_changes_if_needed():
            current = next(key for key, value in self._page_routes.items() if value == self.page_stack.currentIndex())
            self.sidebar.set_active_route(current)
            return False
        index = self._page_routes.get(normalized)
        if index is None:
            return False
        self.page_stack.setCurrentIndex(index)
        self.sidebar.set_active_route(normalized)
        if normalized == "analytics":
            self.analytics_page.refresh(self._selected_day)
        elif normalized == "reports":
            self.reports_page.refresh(self._selected_day)
        elif normalized == "settings":
            self.settings_page.refresh()
            if self._residency_controller is not None:
                self._residency_controller.refresh()
        self._set_status("")
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
        if getattr(self.settings_page, "is_busy", False):
            self._set_status(_("Please wait for the current operation."), notify=True)
            return False
        if self._entry_dirty:
            confirmed = (
                bool(self._config.confirm_discard_changes())
                if self._config.confirm_discard_changes is not None
                else self._ask_discard_changes()
            )
            if not confirmed:
                self._set_status(_("Unsaved changes"))
                return False
        if not self.reports_page.confirm_leave():
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


def _record_summary(form: object) -> tuple[str, ...]:
    worked_hours = float(getattr(form, "worked_hours", 0.0) or 0.0)
    note = str(getattr(form, "note", "") or "").strip()
    work_type = _work_type_label(str(getattr(form, "work_type", "") or ""))
    start_time = getattr(form, "start_time", None)
    end_time = getattr(form, "end_time", None)
    lines: list[str] = []
    if start_time or end_time or worked_hours > 0:
        time_text = f"{start_time or '--:--'} - {end_time or '--:--'}"
        lines.append(f"{time_text}  {worked_hours:.1f}{_('h')}")
    if work_type and (lines or bool(getattr(form, "is_leave", False))):
        lines.append(work_type)
    if note:
        lines.append(note)
    return tuple(lines)


def _work_type_label(work_type: str) -> str:
    labels = {
        "normal": _("Normal"),
        "remote": _("Remote"),
        "business_trip": _("Business trip"),
        "paid_leave": _("Paid leave"),
        "comp_leave": _("Comp leave"),
        "sick_leave": _("Sick leave"),
    }
    return labels.get(work_type, "")
