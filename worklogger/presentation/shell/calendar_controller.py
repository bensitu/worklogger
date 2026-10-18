"""Coordinate calendar queries, entry editing, and account preferences."""

from dataclasses import replace
from copy import copy
from datetime import date

from worklogger.domain.shared.result import Result
from worklogger.presentation.date_labels import month_label
from worklogger.presentation.job_runner import owned_callback
from worklogger.domain.shared.errors import InfrastructureError


class CalendarCoordinator:
    def __init__(
        self,
        *,
        calendar_view_model,
        stats_view_model,
        calendar_page,
        entry_panel,
        stats_panel,
    ):
        self._calendar = calendar_view_model
        self._stats = stats_view_model
        self._page = calendar_page
        self._entries = entry_panel
        self._stats_panel = stats_panel
        self._revision = 0
        self._handle = None

    def invalidate(self):
        self._revision += 1
        if self._handle is not None:
            self._handle.cancel()
        self._handle = None
        self._page.calendar_view.set_loading(False)

    def refresh_overview(self, runner, *, config, month, selected_day, today, holidays, on_error,
                         load_entries=True, on_entries_loaded=None):
        self._revision += 1
        revision = self._revision
        if self._handle is not None:
            self._handle.cancel()
        calendar, stats = copy(self._calendar), copy(self._stats)
        if load_entries and self._entries.view_model.draft.day != selected_day:
            self._page.set_time_entries((), ())
        entries_request = self._entries.prepare_day_load(selected_day) if load_entries else None
        holidays = dict(holidays) if holidays is not None else None
        self._page.set_month_title(month_label(month), month)
        self._page.month_picker_button.set_week_start_monday(config.calendar_options.week_start_monday)
        self._page.calendar_view.set_loading(True)
        def work(_token):
            calendar_result = calendar.build_month(year=month.year, month=month.month,
                selected_day=selected_day, today=today, holidays=holidays,
                options=replace(config.calendar_options, standard_work_hours=float(config.standard_work_hours)),
                theme=config.theme, dark=config.dark, custom_color=config.custom_color)
            stats_result = stats.build_month(year=month.year, month=month.month,
                standard_work_hours=config.standard_work_hours, monthly_target_hours=config.monthly_target_hours)
            entries = entries_request() if entries_request is not None else None
            events = calendar.events_for_day(selected_day) if entries is not None else None
            return calendar_result, stats_result, entries, events
        def complete(result):
            if revision != self._revision:
                return
            self._handle = None
            self._page.calendar_view.set_loading(False)
            if not result.ok:
                on_error(result.error)
                return
            calendar_result, stats_result, entries, events = result.value
            if calendar_result.ok and calendar_result.value is not None:
                self._page.calendar_view.set_state(calendar_result.value)
            else:
                on_error(calendar_result.error)
            if stats_result.ok and stats_result.value is not None:
                self._stats_panel.set_state(stats_result.value)
            else:
                on_error(stats_result.error)
            if entries is not None and not self._entries.is_busy:
                if entries.ok and events.ok:
                    records, latest_change = entries.value
                    self._entries.apply_day_records(records, latest_change)
                    self._page.set_time_entries(records, events.value or ())
                    if on_entries_loaded is not None:
                        on_entries_loaded()
                else:
                    on_error(entries.error or events.error)
        try:
            self._handle = runner.submit("load_calendar_overview", work, on_complete=owned_callback(self._page, complete))
            return True
        except Exception:
            self._page.calendar_view.set_loading(False)
            on_error(InfrastructureError("calendar_load_failed", "calendar_load_failed"))
            return False

    def refresh_calendar(self, *, config, month, selected_day, today, holidays):
        self.invalidate()
        options = replace(
            config.calendar_options,
            standard_work_hours=float(config.standard_work_hours),
        )
        result = self._calendar.build_month(
            year=month.year,
            month=month.month,
            selected_day=selected_day,
            today=today,
            holidays=holidays,
            options=options,
            theme=config.theme,
            dark=config.dark,
            custom_color=config.custom_color,
        )
        if not result.ok or result.value is None:
            return result
        self._page.calendar_view.set_state(result.value)
        self._page.set_month_title(
            month_label(date(result.value.year, result.value.month, 1)), month
        )
        self._page.month_picker_button.set_week_start_monday(config.calendar_options.week_start_monday)
        return Result.success(None)

    def refresh_entries(self, day):
        entries = self._entries.load_day(day)
        events = self._calendar.events_for_day(day)
        if not entries.ok or not events.ok:
            return Result.failure(entries.error or events.error)
        self._page.set_time_entries(entries.value, events.value or ())
        return Result.success(self._entries.is_dirty)

    def refresh_statistics(self, config, month):
        result = self._stats.build_month(
            year=month.year,
            month=month.month,
            standard_work_hours=config.standard_work_hours,
            monthly_target_hours=config.monthly_target_hours,
        )
        if not result.ok or result.value is None:
            return result
        self._stats_panel.set_state(result.value)
        return Result.success(None)


def apply_recording_preferences(
    config, state, *, time_entries, reports=None, analytics=None
):
    updated = replace(
        config,
        theme=state.theme,
        dark=state.dark_mode,
        custom_color=state.custom_color,
        standard_work_hours=state.standard_work_hours,
        monthly_target_hours=state.monthly_target_hours,
        show_recent_context=state.show_recent_context,
        calendar_options=replace(
            config.calendar_options,
            show_holidays=state.show_holidays,
            holiday_region=state.holiday_region,
            show_note_markers=state.show_note_markers,
            show_overnight_indicator=state.show_overnight_indicator,
            week_start_monday=state.week_start_monday,
        ),
    )
    time_entries.set_default_break_hours(state.default_break_hours)
    time_entries.set_timer_reminders(state.timer_reminder_hours, state.continuous_timer_reminder_hours)
    for model in (reports, analytics):
        if hasattr(model, "set_standard_work_hours"):
            model.set_standard_work_hours(state.standard_work_hours)
        if hasattr(model, "set_week_start_monday"):
            model.set_week_start_monday(state.week_start_monday)
    return updated
