"""Coordinate calendar queries, entry editing, and account preferences."""

from dataclasses import replace
from datetime import date

from worklogger.domain.shared.result import Result
from worklogger.presentation.date_labels import month_label


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

    def refresh_calendar(self, *, config, month, selected_day, today, holidays):
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
            month_label(date(result.value.year, result.value.month, 1))
        )
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
    if hasattr(reports, "set_standard_work_hours"):
        reports.set_standard_work_hours(state.standard_work_hours)
    for model in (reports, analytics):
        if hasattr(model, "set_week_start_monday"):
            model.set_week_start_monday(state.week_start_monday)
    return updated
