"""Minimal work-log entry shell."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, timedelta

from PySide6.QtCore import QEvent, QTimer, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from worklogger.domain.shared.errors import AppError
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.settings import SettingsWorkflow
from worklogger.presentation.shell.background_controller import BackgroundController
from worklogger.presentation.shell.residency import QtResidencyController
from worklogger.presentation.theme import ThemeEngine, configure_application_style, install_bundled_fonts
from worklogger.presentation.theme.background import MainBackgroundWidget
from worklogger.presentation.viewmodels.time_entries import TimeEntryViewModel
from worklogger.presentation.widgets.assets import apply_window_icon
from worklogger.presentation.widgets._style import refresh_style_tree
from worklogger.presentation.widgets.icons import set_button_icon
from worklogger.presentation.widgets.status_label import StatusLabel
from worklogger.presentation.widgets.date_picker import DatePickerButton
from worklogger.presentation.widgets.date_picker_holidays import DatePickerHolidaysController
from worklogger.presentation.widgets.time_entries import TimeEntryPanel
from worklogger.presentation.widgets.time_entry_history import TimeEntryHistory


@dataclass(frozen=True)
class MinimalViewConfig:
    selected_day: date | None = None
    today: date | None = None
    account_name: str | None = None
    show_recent_context: bool = True
    confirm_discard_changes: Callable[[], bool] | None = None
    theme: str = "blue"
    dark: bool = False
    custom_color: str | None = None
    background_images_available: bool = True
    week_start_monday: bool = False
    show_holidays: bool = True
    holiday_region: str = ""


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
        background_service=None,
        holidays_handler=None,
        holiday_country="",
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
        self._settings_dialog = None
        self._refresh_pending = False

        self.setObjectName("minimal_view")
        self.setWindowTitle(_("WorkLogger"))
        apply_window_icon(self)
        self._build_ui()
        self.date_picker_holidays = DatePickerHolidaysController(self.date_button, holidays_handler,
            country=holiday_country, enabled=self._config.show_holidays, region=self._config.holiday_region,
            job_runner=self._job_runner)
        self.apply_theme()
        self.background_controller = BackgroundController(self._background_surface, background_service,
            available=self._config.background_images_available, job_runner=self._job_runner)
        self._background_surface.active_changed.connect(lambda _active: refresh_style_tree(self._background_surface))
        self.background_controller.reload()
        self._connect_signals()
        self.resize(680, 760)
        self.setMinimumSize(640, 640)
        if hasattr(self._residency_controller, "notify_timer_reminder"):
            self.entry_panel.reminder.connect(self._residency_controller.notify_timer_reminder)
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
            if hasattr(self._residency_controller, "bind_recording"):
                self._residency_controller.bind_recording(start_callback=self.entry_panel.start_recording,
                    end_callback=self.entry_panel.end_recording, state_probe=self.entry_panel.recording_action_state)
                self.entry_panel.recording_changed.connect(self._residency_controller.update_recording_actions)
                self.entry_panel.busy_changed.connect(lambda _busy: self._residency_controller.update_recording_actions())

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
        if self.entry_panel.is_busy:
            self._refresh_pending = True
            return False
        self._refresh_pending = False
        self._last_error = None
        self.date_button.set_date(self._selected_day)
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
        if self.entry_panel.is_busy:
            return False
        if day != self._selected_day and not self._confirm_discard_changes_if_needed():
            return False
        self._selected_day = day
        return self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._background_surface = MainBackgroundWidget(self)
        outer.addWidget(self._background_surface)
        root = QVBoxLayout(self._background_surface)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        nav = QGridLayout()
        nav.setColumnStretch(0, 1)
        nav.setColumnStretch(2, 1)
        self.previous_button = QPushButton("<")
        self.previous_button.setToolTip(_("Previous day"))
        self.previous_button.setAccessibleName(_("Previous day"))
        self.previous_button.setProperty("variant", "outline")
        self.previous_button.setFixedWidth(40)
        set_button_icon(self.previous_button, "chevron-left")
        self.previous_button.setText("")
        self.today_button = QPushButton(_("Today"))
        self.next_button = QPushButton(">")
        self.next_button.setToolTip(_("Next day"))
        self.next_button.setAccessibleName(_("Next day"))
        self.next_button.setProperty("variant", "outline")
        self.next_button.setFixedWidth(40)
        set_button_icon(self.next_button, "chevron-right")
        self.next_button.setText("")
        self.date_button = DatePickerButton(week_start_monday=self._config.week_start_monday)
        self.account_label = QLabel("")
        self.account_label.setTextFormat(Qt.TextFormat.PlainText)
        self.account_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.account_label.setWordWrap(True)
        self.account_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.account_label.setObjectName("minimal_account_label")
        self.account_label.setProperty("role", "secondary")
        self.settings_button = QPushButton(_("Settings"))
        self.settings_button.setObjectName("minimal_settings_button")
        self.settings_button.setToolTip(_("Settings"))
        set_button_icon(self.settings_button, "settings")
        nav.addWidget(self.today_button, 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.date_navigation_widget = QWidget()
        self.date_navigation_widget.setObjectName("minimal_date_navigation_widget")
        date_navigation = QHBoxLayout(self.date_navigation_widget)
        date_navigation.setContentsMargins(0, 0, 0, 0)
        date_navigation.setSpacing(8)
        date_navigation.addWidget(self.previous_button)
        date_navigation.addWidget(self.date_button)
        date_navigation.addWidget(self.next_button)
        nav.addWidget(self.date_navigation_widget, 0, 1)
        self.notes_button = QPushButton(_("Notes"))
        set_button_icon(self.notes_button, "notebook-text")
        self.notes_button.setVisible(self._notes_workflow is not None)
        nav.addWidget(self.account_label, 0, 2)
        self.settings_button.setVisible(self._settings_workflow is not None)
        root.addLayout(nav)
        actions = QHBoxLayout()
        self.new_record_button = QPushButton(_("New time record"))
        self.new_record_button.setProperty("variant", "primary")
        set_button_icon(self.new_record_button, "plus")
        actions.addWidget(self.new_record_button)
        actions.addStretch(1)
        actions.addWidget(self.notes_button)
        actions.addWidget(self.settings_button)
        root.addLayout(actions)

        self.entry_panel = TimeEntryPanel(self._time_entry_view_model, compact=False, job_runner=self._job_runner)
        self.entry_panel.context_picker.recent_button.setVisible(self._config.show_recent_context)
        root.addWidget(self.entry_panel)
        self.records_title_label = QLabel(_("Time records"))
        self.records_title_label.setProperty("role", "section_heading")
        root.addWidget(self.records_title_label)
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
        self.date_button.date_selected.connect(self.select_day)
        self.settings_button.clicked.connect(self.open_settings)
        self.notes_button.clicked.connect(self.open_notes)
        self.new_record_button.clicked.connect(self.entry_panel.new_record)
        self.entry_panel.records_changed.connect(self._entries_changed)
        self.entry_panel.dirty_changed.connect(lambda dirty: setattr(self, "_entry_dirty", dirty))
        self.entry_panel.selection_changed.connect(self.history_widget.set_selected_entry)
        self.history_widget.entry_selected.connect(self.entry_panel.edit_entry)
        self.history_widget.entry_delete_requested.connect(self.entry_panel.delete_entry)
        self.history_widget.entry_actions_requested.connect(self.entry_panel.record_actions)
        self.entry_panel.busy_changed.connect(self._set_entry_busy)

    def _set_entry_busy(self, busy):
        self.history_widget.setDisabled(busy)
        for button in (self.previous_button, self.today_button, self.next_button, self.date_button, self.new_record_button,
                       self.notes_button, self.settings_button):
            button.setEnabled(not busy)
        if not busy and self._refresh_pending:
            QTimer.singleShot(0, self, self._refresh_after_job)

    def _refresh_after_job(self):
        if self._refresh_pending and not self.entry_panel.is_busy:
            self.refresh()

    def apply_theme(self):
        engine = ThemeEngine()
        self.date_button.set_colors(engine.palette(self._config.theme, dark=self._config.dark,
                                                  custom_color=self._config.custom_color))
        self._background_surface.set_base_color(engine.palette(self._config.theme, dark=self._config.dark,
                                                              custom_color=self._config.custom_color).surface)
        application = QApplication.instance()
        if application is not None:
            configure_application_style()
            install_bundled_fonts()
            palette = engine.qt_palette(self._config.theme, dark=self._config.dark, custom_color=self._config.custom_color)
            stylesheet = engine.application_stylesheet(self._config.theme, dark=self._config.dark, custom_color=self._config.custom_color)
            if application.palette() != palette:
                application.setPalette(palette)
            if application.styleSheet() != stylesheet:
                application.setStyleSheet(stylesheet)

    def _entries_changed(self, day: date):
        model = self.entry_panel.view_model
        preserve_day = model.manual_dirty and model.draft.day != day
        if not preserve_day and (self.entry_panel.time_tabs.currentIndex() == 1 or model.editing_active_timer):
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
        self.background_controller.dispose()
        self.date_picker_holidays.dispose()
        self._background_surface.shutdown()
        self._date_timer.stop()
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

    def hideEvent(self, event):
        self._date_timer.stop()
        super().hideEvent(event)

    def showEvent(self, event):
        if self._config.today is None:
            self._date_timer.start()
            self._update_today()
        super().showEvent(event)

    def _confirm_discard_changes_if_needed(self) -> bool:
        modal = QApplication.activeModalWidget()
        if modal is not None and modal is not self._settings_dialog and self.isAncestorOf(modal):
            return False
        if (self._settings_dialog is not None and hasattr(self._settings_dialog, "confirm_profile_leave")
                and not self._settings_dialog.confirm_profile_leave()):
            return False
        if bool(getattr(self._notes_workflow, "is_open", False)):
            self._set_status(_("Close the note editor before continuing."))
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

    def apply_user_profile(self, user):
        self._config = replace(self._config, account_name=user.effective_display_name)
        self.account_label.setText(self._account_text())
        self.account_label.setToolTip(user.effective_display_name)

    def _request_logout(self) -> None:
        if not self._confirm_discard_changes_if_needed():
            return
        self._set_status(_("Logout requested"))
        self.logout_requested.emit()

    def open_settings(self) -> bool:
        if (self._settings_workflow is None or self.entry_panel.is_busy or self._settings_dialog is not None
                or bool(getattr(self._notes_workflow, "is_open", False))):
            return False
        logged_out = False
        if hasattr(self._settings_workflow, "create_dialog"):
            dialog = self._settings_workflow.create_dialog(self)
            self._settings_dialog = dialog
            if hasattr(dialog, "background_settings"):
                dialog.background_settings.bind(self.background_controller)
                self.background_controller.reload()
            if hasattr(dialog, "profile_changed"):
                dialog.profile_changed.connect(self.apply_user_profile)
            if hasattr(dialog, "work_types_changed"):
                dialog.work_types_changed.connect(self.entry_panel.refresh_work_types)
            if hasattr(dialog, "projects_changed"):
                dialog.projects_changed.connect(self.entry_panel.refresh_projects)
            if hasattr(dialog, "settings_changed"):
                dialog.settings_changed.connect(self._apply_recording_settings)
            if hasattr(dialog, "ai_availability_changed"):
                dialog.ai_availability_changed.connect(self.entry_panel.refresh_ai_availability)
            self.entry_panel.refresh_ai_availability()

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
                self._settings_dialog = None
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
        if (self._notes_workflow is None or self.entry_panel.is_busy or self._settings_dialog is not None
                or bool(getattr(self._notes_workflow, "is_open", False))):
            return False
        self._notes_workflow.open(self._selected_day, self)
        self.refresh()
        return True

    def _apply_recording_settings(self, state):
        self._time_entry_view_model.set_default_break_hours(state.default_break_hours)
        self._config = replace(self._config, show_recent_context=state.show_recent_context,
                               theme=state.theme, dark=state.dark_mode, custom_color=state.custom_color,
                               week_start_monday=state.week_start_monday, show_holidays=state.show_holidays,
                               holiday_region=state.holiday_region)
        self.date_button.set_week_start_monday(state.week_start_monday)
        self.date_picker_holidays.configure(enabled=state.show_holidays, region=state.holiday_region)
        self.entry_panel.context_picker.recent_button.setVisible(state.show_recent_context)
        self._time_entry_view_model.set_timer_reminders(state.timer_reminder_hours, state.continuous_timer_reminder_hours)
        self.apply_theme()

    def _restore_from_residency(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit_from_residency(self) -> None:
        if not self._confirm_discard_changes_if_needed():
            return
        if self._residency_controller is not None:
            self._residency_controller.request_quit()
        self.close()
