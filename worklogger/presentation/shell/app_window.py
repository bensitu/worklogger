"""Qt application window composing navigation and presentation workflows."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Protocol

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from worklogger.app.job_runner import JobRunner
from worklogger.app.use_cases.backgrounds import BackgroundService
from worklogger.domain.shared.dates import add_months
from worklogger.domain.shared.errors import AppError, CancellationError, InfrastructureError
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.settings import SettingsWorkflow
from worklogger.presentation.shell.calendar_controller import (
    CalendarCoordinator,
    apply_recording_preferences,
)
from worklogger.presentation.shell.pages import (
    AnalyticsPage,
    CalendarPage,
    ReportsPage,
    UnavailableSettingsPage,
)
from worklogger.presentation.shell.residency import QtResidencyController
from worklogger.presentation.shell.appearance_controller import WindowAppearanceController
from worklogger.presentation.shell.lifecycle_controller import WindowLifecycleController
from worklogger.presentation.shell.menu_bar import install_application_menu
from worklogger.presentation.shell.record_dialogs import RecordDialogController
from worklogger.presentation.theme.background import MainBackgroundWidget
from worklogger.presentation.theme import ThemeEngine
from worklogger.presentation.viewmodels import (
    CalendarDisplayOptions,
    CalendarViewModel,
    SettingsState,
    StatsPanelViewModel,
)
from worklogger.presentation.viewmodels.time_entries import TimeEntryViewModel
from worklogger.presentation.widgets import (
    CalendarView,
    SidebarWidget,
    StatsPanel,
)
from worklogger.presentation.widgets.assets import apply_window_icon
from worklogger.presentation.widgets.feedback import confirm_discard_record_changes
from worklogger.presentation.widgets.time_entries import TimeEntryPanel


class NotesWorkflow(Protocol):
    def open(self, day: date, parent: QWidget | None = None) -> object: ...


class AnalyticsWorkflow(Protocol):
    def open(self, day: date, parent: QWidget | None = None) -> object: ...


class ReportsWorkflow(Protocol):
    def open(self, day: date, parent: QWidget | None = None) -> object: ...


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
    profile_avatar_png: str = field(default="", repr=False)
    show_recent_context: bool = True
    background_images_available: bool = True
    confirm_discard_changes: Callable[[], bool] | None = None


class AppWindow(QMainWindow):
    logout_requested = Signal()

    def __init__(
        self,
        *,
        calendar_view_model: CalendarViewModel,
        time_entry_view_model: TimeEntryViewModel,
        stats_panel_view_model: StatsPanelViewModel,
        config: AppWindowConfig | None = None,
        settings_workflow: SettingsWorkflow | None = None,
        analytics_workflow: AnalyticsWorkflow | None = None,
        notes_workflow: NotesWorkflow | None = None,
        reports_workflow: ReportsWorkflow | None = None,
        residency_controller: QtResidencyController | None = None,
        theme_engine: ThemeEngine | None = None,
        job_runner: JobRunner | None = None,
        background_service: BackgroundService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._calendar_view_model = calendar_view_model
        self._time_entry_view_model = time_entry_view_model
        self._stats_panel_view_model = stats_panel_view_model
        self._config = config or AppWindowConfig()
        self._settings_workflow = settings_workflow
        self._analytics_workflow = analytics_workflow
        self._notes_workflow = notes_workflow
        self._reports_workflow = reports_workflow
        reports_model = getattr(reports_workflow, "view_model", None)
        if hasattr(reports_model, "set_standard_work_hours"):
            reports_model.set_standard_work_hours(self._config.standard_work_hours)
        if hasattr(reports_model, "set_week_start_monday"):
            reports_model.set_week_start_monday(
                self._config.calendar_options.week_start_monday
            )
        analytics_model = getattr(analytics_workflow, "view_model", None)
        if hasattr(analytics_model, "set_standard_work_hours"):
            analytics_model.set_standard_work_hours(self._config.standard_work_hours)
        if hasattr(analytics_model, "set_week_start_monday"):
            analytics_model.set_week_start_monday(
                self._config.calendar_options.week_start_monday
            )
        self._residency_controller = residency_controller
        self._job_runner = job_runner
        self._today = self._config.today or date.today()
        timer = time_entry_view_model.timer
        restored_day = timer.started_at.date() if timer else None
        self._selected_day = self._config.selected_day or restored_day or self._today
        self._current_month = self._selected_day.replace(day=1)
        # None requests regional holidays; an explicit mapping overrides the provider.
        self._holidays = (
            None if self._config.holidays is None else dict(self._config.holidays)
        )
        self._last_error: AppError | None = None
        self._refreshing = False
        self._entry_dirty = False
        self._records_refresh_pending = False
        self._work_plan_settings = None

        self.setObjectName("app_window")
        self.setWindowTitle(_("WorkLogger"))
        apply_window_icon(self)
        self._build_ui()
        self.appearance_controller = WindowAppearanceController(
            self, self._background_surface, theme_engine=theme_engine, background_service=background_service,
            background_images_available=self._config.background_images_available, job_runner=self._job_runner,
        )
        self.background_controller = self.appearance_controller.background
        self.glass_controller = self.appearance_controller.glass
        self._calendar_coordinator = CalendarCoordinator(
            calendar_view_model=self._calendar_view_model,
            stats_view_model=self._stats_panel_view_model,
            calendar_page=self.calendar_page,
            entry_panel=self.entry_panel,
            stats_panel=self.stats_panel,
        )
        self.record_dialogs = RecordDialogController(self, self._time_entry_view_model,
            analytics=analytics_model, current_month=lambda: self._current_month,
            selected_day=lambda: self._selected_day, select_record=self._open_found_entry,
            records_changed=self._records_associated, job_runner=self._job_runner)
        self._connect_signals()
        self.refresh_ai_availability()
        self.sidebar.set_avatar(self._config.profile_avatar_png)
        self.apply_theme()
        self.background_controller.reload()
        self.lifecycle_controller = WindowLifecycleController(self, self.entry_panel,
            residency=self._residency_controller, confirm_close=self._confirm_discard_changes_if_needed,
            update_today=self._update_today, poll_dates=self._config.today is None,
            close_callbacks=(self._calendar_coordinator.invalidate, self.appearance_controller.dispose))
        self.application_menu = install_application_menu(
            self, new_record=self.new_record, save_target=self._menu_save_target,
            settings=self.open_settings if self._settings_workflow is not None else None,
            routes={"calendar": lambda: self._switch_route("calendar"),
                    "analytics": self.open_analytics if self._analytics_workflow is not None else None,
                    "reports": self.open_reports if self._reports_workflow is not None else None,
                    "settings": self.open_settings if self._settings_workflow is not None else None},
            quit_app=self.lifecycle_controller.request_quit,
        )
        if self.application_menu is not None:
            self.page_stack.currentChanged.connect(self.application_menu.refresh)
            self.entry_panel.busy_changed.connect(self.application_menu.refresh)

    def new_record(self) -> bool:
        return self._switch_route("calendar") and self.entry_panel.new_record()

    def _menu_save_target(self):
        page = self.page_stack.currentWidget()
        if page is self.calendar_page:
            return self.entry_panel.save_button
        if page is self.reports_page:
            return self.reports_page.save_button
        return None

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
    def settings_page(self) -> QWidget:
        if self._settings_page is None:
            page = self._settings_workflow.create_page(self)
            self._settings_page = page
            index = self._page_routes["settings"]
            placeholder = self.page_stack.widget(index)
            self.page_stack.insertWidget(index, page)
            self.page_stack.removeWidget(placeholder)
            placeholder.deleteLater()
            self._connect_settings_page(page)
            if hasattr(page, "background_settings"):
                page.background_settings.bind(self.background_controller)
            self.glass_controller.refresh_surfaces()
            self.refresh_ai_availability()
        return self._settings_page

    @property
    def has_unsaved_changes(self) -> bool:
        return self._entry_dirty or self.reports_page.has_unsaved_changes

    def apply_theme(self, *, force: bool = False) -> None:
        colors = self.appearance_controller.apply(
            self._config.theme, dark=self._config.dark, custom_color=self._config.custom_color,
            force=force,
        )
        if colors is not None:
            self.calendar_page.month_picker_button.set_colors(colors)

    def apply_settings(self, state: SettingsState) -> None:
        self.sidebar.set_avatar(state.profile_avatar_png)
        self.entry_panel.set_recent_context_visible(state.show_recent_context)
        previous_config = self._config
        self._config = apply_recording_preferences(
            self._config,
            state,
            time_entries=self._time_entry_view_model,
            reports=getattr(self._reports_workflow, "view_model", None),
            analytics=getattr(self._analytics_workflow, "view_model", None),
        )
        self.apply_theme()
        work_plan = (state.work_schedule, state.work_target_mode)
        if previous_config != self._config or work_plan != self._work_plan_settings:
            if self._job_runner is not None:
                self._calendar_coordinator.refresh_overview(self._job_runner, config=self._config,
                    month=self._current_month, selected_day=self._selected_day, today=self._today,
                    holidays=self._holidays, on_error=self._set_error)
            else:
                self._refresh_calendar()
                self._refresh_stats()
        self._work_plan_settings = work_plan
        if self._residency_controller is not None:
            self._residency_controller.refresh()

    def refresh(self, *, asynchronous=False, on_entries_loaded=None) -> bool:
        if asynchronous and self._job_runner is not None:
            overview_ok = self._calendar_coordinator.refresh_overview(self._job_runner,
                config=self._config, month=self._current_month, selected_day=self._selected_day,
                today=self._today, holidays=self._holidays, on_error=self._set_error,
                on_entries_loaded=on_entries_loaded)
            return overview_ok
        self._last_error = None
        self._refreshing = True
        try:
            calendar_ok = self._refresh_calendar()
            entry_ok = self._refresh_entry()
            stats_ok = self._refresh_stats()
        finally:
            self._refreshing = False
        if calendar_ok and entry_ok and stats_ok:
            if on_entries_loaded is not None:
                on_entries_loaded()
            self._set_status("")
            return True
        self._set_error(self._last_error)
        return False

    def select_day(self, day: date, *, asynchronous=False, on_entries_loaded=None) -> bool:
        if day != self._selected_day and not self._confirm_discard_changes_if_needed():
            return False
        self._selected_day = day
        self._current_month = day.replace(day=1)
        return self.refresh(asynchronous=asynchronous, on_entries_loaded=on_entries_loaded)

    def previous_month(self, *, asynchronous=False) -> bool:
        if not self._confirm_discard_changes_if_needed():
            return False
        self._current_month = add_months(self._current_month, -1)
        return self.refresh(asynchronous=asynchronous)

    def next_month(self, *, asynchronous=False) -> bool:
        if not self._confirm_discard_changes_if_needed():
            return False
        self._current_month = add_months(self._current_month, 1)
        return self.refresh(asynchronous=asynchronous)

    def go_today(self, *, asynchronous=False) -> bool:
        self._update_today()
        if (
            self._today != self._selected_day
            and not self._confirm_discard_changes_if_needed()
        ):
            return False
        self._selected_day = self._today
        self._current_month = self._today.replace(day=1)
        return self.refresh(asynchronous=asynchronous)

    def _update_today(self) -> None:
        current = self._config.today or date.today()
        if self._today != current:
            self._today = current
            self.analytics_page.set_today(current)
            self.refresh(asynchronous=self._job_runner is not None)

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

        main = MainBackgroundWidget()
        self._background_surface = main
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        root.addWidget(main, 1)

        self.page_stack = QStackedWidget()
        self.page_stack.setObjectName("app_page_stack_widget")
        main_layout.addWidget(self.page_stack, 1)

        self.calendar_view = CalendarView()
        self.entry_panel = TimeEntryPanel(
            self._time_entry_view_model, job_runner=self._job_runner
        )
        self.entry_panel.set_recent_context_visible(self._config.show_recent_context)
        self.stats_panel = StatsPanel()
        self.calendar_page = CalendarPage(
            calendar_view=self.calendar_view,
            entry_panel=self.entry_panel,
            stats_panel=self.stats_panel,
        )
        self.analytics_page = AnalyticsPage(
            getattr(self._analytics_workflow, "view_model", None),
            self._selected_day,
            job_runner=self._job_runner, today=self._today,
        )
        self.reports_page = ReportsPage(
            getattr(self._reports_workflow, "view_model", None),
            self._selected_day,
            job_runner=self._job_runner,
            confirm_discard=self._config.confirm_discard_changes,
        )
        if hasattr(self._settings_workflow, "create_page"):
            self._settings_page = None
            settings_placeholder = QWidget(self.page_stack)
        else:
            self._settings_page = UnavailableSettingsPage()
            settings_placeholder = self._settings_page

        self._page_routes = {
            "calendar": self.page_stack.addWidget(self.calendar_page),
            "analytics": self.page_stack.addWidget(self.analytics_page),
            "reports": self.page_stack.addWidget(self.reports_page),
            "settings": self.page_stack.addWidget(settings_placeholder),
        }

        self.previous_month_button = self.calendar_page.previous_month_button
        self.today_button = self.calendar_page.today_button
        self.next_month_button = self.calendar_page.next_month_button
        self.notes_button = self.calendar_page.notes_button
        self.reports_button = self.sidebar.button("reports")
        self.analytics_button = self.sidebar.button("analytics")
        self.settings_button = self.sidebar.settings_button
        self.status_label = QLabel("")
        self.status_label.setObjectName("app_status_label")
        self.status_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.status_label.hide()

        self.notes_button.setVisible(self._notes_workflow is not None)
        main_layout.addWidget(self.status_label)

    def _connect_signals(self) -> None:
        self.sidebar.route_changed.connect(self._switch_route)
        self.calendar_page.previous_month_requested.connect(lambda: self.previous_month(asynchronous=True))
        self.calendar_page.today_requested.connect(lambda: self.go_today(asynchronous=True))
        self.calendar_page.next_month_requested.connect(lambda: self.next_month(asynchronous=True))
        self.calendar_page.search_requested.connect(self.open_record_search)
        self.calendar_page.date_selected.connect(lambda day: self.select_day(day, asynchronous=True))
        self.analytics_page.projects_requested.connect(self.open_project_analytics)
        self.notes_button.clicked.connect(self.open_notes)
        self.calendar_view.day_selected.connect(lambda day: self.select_day(day, asynchronous=True))
        self.entry_panel.records_changed.connect(self._entries_changed)
        self.entry_panel.dirty_changed.connect(
            lambda dirty: setattr(self, "_entry_dirty", dirty)
        )
        self.entry_panel.busy_changed.connect(
            self.calendar_page.records_widget.setDisabled
        )
        self.entry_panel.busy_changed.connect(self._record_update_state)
        self.calendar_page.entry_selected.connect(self.entry_panel.edit_entry)
        self.calendar_page.entry_delete_requested.connect(self.entry_panel.delete_entry)
        self.calendar_page.entry_actions_requested.connect(self.entry_panel.record_actions)
        self.entry_panel.selection_changed.connect(
            self.calendar_page.set_selected_entry
        )
        self.calendar_page.event_selected.connect(self.entry_panel.copy_event)
        self.calendar_page.event_delete_requested.connect(self.entry_panel.delete_event)

    def _connect_settings_page(self, page) -> None:
        for name, callback in (
            ("logout_requested", self._request_logout),
            ("settings_changed", self.apply_settings),
            ("profile_changed", self.apply_user_profile),
            ("entry_types_changed", self.entry_panel.refresh_entry_types),
            ("projects_changed", self.entry_panel.refresh_projects),
            ("records_recovered", lambda: self._entries_changed(self._selected_day)),
            ("data_imported", self._records_associated),
            ("ai_availability_changed", self.refresh_ai_availability),
        ):
            signal = getattr(page, name, None)
            if signal is not None:
                signal.connect(callback)

    def open_project_analytics(self) -> None:
        self.record_dialogs.open_project_analytics()

    def open_record_search(self) -> None:
        self.record_dialogs.open_search()

    def _records_associated(self):
        if self.entry_panel.is_busy:
            self._records_refresh_pending = True
            return
        self.refresh(asynchronous=self._job_runner is not None)
        self.entry_panel.refresh_projects()

    def _record_update_state(self, busy):
        if not busy and self._records_refresh_pending:
            self._records_refresh_pending = False
            QTimer.singleShot(0, self, self._records_associated)

    def _open_found_entry(self, record):
        if self.entry_panel.is_busy or not self._switch_route("calendar"):
            return False
        if self._job_runner is not None:
            return self.select_day(record.day, asynchronous=True,
                                   on_entries_loaded=lambda: self.entry_panel.edit_entry(record))
        if not self.select_day(record.day):
            return False
        self.entry_panel.edit_entry(record)
        original = self._time_entry_view_model.draft.original
        return original is not None and original.id == record.id

    def _entries_changed(self, day: date) -> None:
        preserve_day = self._time_entry_view_model.manual_dirty and self._time_entry_view_model.draft.day != day
        if not preserve_day and (self.entry_panel.time_tabs.currentIndex() == 1 or self._time_entry_view_model.editing_active_timer):
            self._selected_day = day
            self._current_month = day.replace(day=1)
        self.refresh(asynchronous=self._job_runner is not None)

    def refresh_ai_availability(self):
        self.entry_panel.refresh_ai_availability()
        self.reports_page.refresh_ai_availability()
        if hasattr(self._notes_workflow, "refresh_ai_availability"):
            self._notes_workflow.refresh_ai_availability()

    def _refresh_calendar(self) -> bool:
        result = self._calendar_coordinator.refresh_calendar(
            config=self._config,
            month=self._current_month,
            selected_day=self._selected_day,
            today=self._today,
            holidays=self._holidays,
        )
        if not result.ok:
            self._set_error(result.error)
        return result.ok

    def _refresh_entry(self) -> bool:
        result = self._calendar_coordinator.refresh_entries(self._selected_day)
        if not result.ok:
            self._set_error(result.error)
            return False
        self._entry_dirty = result.value
        return True

    def _refresh_stats(self) -> bool:
        result = self._calendar_coordinator.refresh_statistics(
            self._config, self._current_month
        )
        if not result.ok:
            self._set_error(result.error)
        return result.ok

    def _set_error(self, error: AppError | None) -> None:
        if isinstance(error, CancellationError):
            self._last_error = None
            self._set_status(display_error_message(error))
            return
        self._last_error = error
        self._set_status(
            display_error_message(error), notify=False, error=True
        )

    def _set_status(
        self, message: str, *, notify: bool = False, error: bool = False
    ) -> None:
        self.status_label.setText(message)
        self.status_label.setVisible(bool(message) and not notify)
        if message and notify:
            show = QMessageBox.warning if error else QMessageBox.information
            show(self, _("WorkLogger"), message)

    def apply_user_profile(self, user):
        self._config = replace(self._config, account_name=user.effective_display_name)
        self.sidebar.set_profile(user.effective_display_name, self._config.account_role)

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
        if self.entry_panel.is_busy:
            self._set_status(_("Please wait for the current operation."), notify=True)
            return False
        self._notes_workflow.open(self._selected_day, self)
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

    def _switch_route(self, route: str) -> bool:
        normalized = str(route or "calendar").strip().lower()
        if (
            normalized == "analytics"
            and getattr(self._analytics_workflow, "view_model", None) is None
        ):
            opened = self.open_analytics()
            self.sidebar.set_active_route("calendar")
            return opened
        if (
            normalized == "reports"
            and getattr(self._reports_workflow, "view_model", None) is None
        ):
            opened = self.open_reports()
            self.sidebar.set_active_route("calendar")
            return opened
        if normalized == "settings" and not hasattr(
            self._settings_workflow, "create_page"
        ):
            opened = self.open_settings()
            self.sidebar.set_active_route("calendar")
            return opened
        if not self._confirm_discard_changes_if_needed():
            current = next(
                key
                for key, value in self._page_routes.items()
                if value == self.page_stack.currentIndex()
            )
            self.sidebar.set_active_route(current)
            return False
        index = self._page_routes.get(normalized)
        if index is None:
            return False
        settings_created = normalized == "settings" and self._settings_page is None
        try:
            page = self.settings_page if normalized == "settings" else self.page_stack.widget(index)
        except Exception:
            current = next(key for key, value in self._page_routes.items()
                           if value == self.page_stack.currentIndex())
            self.sidebar.set_active_route(current)
            self._set_error(InfrastructureError("settings_load_failed", "settings_load_failed"))
            return False
        self.page_stack.setCurrentWidget(page)
        self.sidebar.set_active_route(normalized)
        if normalized == "analytics":
            self.analytics_page.refresh(self._selected_day)
        elif normalized == "reports":
            self.reports_page.refresh(self._selected_day)
        elif normalized == "settings":
            if not settings_created:
                page.refresh()
            if self._residency_controller is not None:
                self._residency_controller.refresh()
        self._set_status("")
        return True

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self.lifecycle_controller.prepare_close():
            event.ignore()
            return
        super().closeEvent(event)

    def _confirm_discard_changes_if_needed(self) -> bool:
        modal = QApplication.activeModalWidget()
        if modal is not None and self.isAncestorOf(modal):
            return False
        if bool(getattr(self._notes_workflow, "is_open", False)):
            return False
        if isinstance(self.entry_panel, TimeEntryPanel) and self.entry_panel.is_busy:
            self._set_status(_("Please wait for the current operation."), notify=True)
            return False
        if getattr(self._settings_page, "is_busy", False):
            self._set_status(_("Please wait for the current operation."), notify=True)
            return False
        if hasattr(self._settings_page, "confirm_profile_leave") and not self._settings_page.confirm_profile_leave():
            return False
        if self._entry_dirty:
            confirmed = (
                bool(self._config.confirm_discard_changes())
                if self._config.confirm_discard_changes is not None
                else confirm_discard_record_changes(self)
            )
            if not confirmed:
                self._set_status(_("Unsaved changes"))
                return False
            if isinstance(self.entry_panel, TimeEntryPanel):
                self.entry_panel.discard_changes()
        if not self.reports_page.confirm_leave():
            self._set_status(_("Unsaved changes"))
            return False
        self._entry_dirty = False
        return True
