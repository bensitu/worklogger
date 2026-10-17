"""General settings controls."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtWidgets import (
    QComboBox,
    QPushButton,
)

from worklogger.config.constants import (
    DEFAULT_BREAK_HOURS_SETTING_KEY,
    TIMER_REMINDER_HOURS_SETTING_KEY,
    CONTINUOUS_TIMER_REMINDER_HOURS_SETTING_KEY,
    ENABLE_TRAY_SETTING_KEY,
    MONTHLY_TARGET_HOURS_SETTING_KEY,
    WORK_SCHEDULE_SETTING_KEY,
    WORK_TARGET_MODE_SETTING_KEY,
    SHOW_HOLIDAYS_SETTING_KEY,
    SHOW_NOTE_MARKERS_SETTING_KEY,
    SHOW_OVERNIGHT_INDICATOR_SETTING_KEY,
    SHOW_RECENT_CONTEXT_SETTING_KEY,
    STANDARD_WORK_HOURS_SETTING_KEY,
    WEEK_START_MONDAY_SETTING_KEY,
)
from worklogger.infrastructure.i18n import _
from worklogger.presentation.settings.sections.actions import SectionActions
from worklogger.presentation.settings.sections.common import (
    _card_with_form,
    _hours_input,
    _SettingsScrollPage,
    _switch_row,
)
from worklogger.presentation.widgets import SwitchButton
from worklogger.presentation.widgets.icons import set_button_icon
from worklogger.presentation.widgets.work_schedule import WorkScheduleEditor


class GeneralSection(_SettingsScrollPage):
    control_names = (
        "default_break_input",
        "holiday_country_combo",
        "holiday_subdivision_combo",
        "holidays_switch",
        "monthly_target_input",
        "target_mode_combo",
        "work_schedule_editor",
        "note_markers_switch",
        "overnight_switch",
        "recent_context_switch",
        "residency_switch",
        "standard_hours_input",
        "week_start_switch",
        "manage_entry_types_button",
        "manage_projects_button",
        "timer_reminder_input",
        "continuous_timer_reminder_input",
    )

    def __init__(self, actions: SectionActions, *, holiday_regions: Mapping[str, tuple[str, ...]],
                 system_country: str):
        super().__init__()
        page = self
        card = _card_with_form(_("Work plan"))
        form = card.form_layout

        self.standard_hours_input = _hours_input(1.0, 24.0, 0.5)
        self.standard_hours_input.valueChanged.connect(
            lambda value: actions.set_number(STANDARD_WORK_HOURS_SETTING_KEY, value)
        )
        form.addRow(_("Daily standard hours (h)"), self.standard_hours_input)

        self.work_schedule_editor = WorkScheduleEditor()
        self.work_schedule_editor.schedule_changed.connect(lambda value: actions.set_text(WORK_SCHEDULE_SETTING_KEY, value))
        form.addRow(_("Work schedule"), self.work_schedule_editor)
        page.layout().addWidget(card)

        card = _card_with_form(_("Hours goal"))
        form = card.form_layout
        self.target_mode_combo = QComboBox()
        self.target_mode_combo.setFixedWidth(320)
        self.target_mode_combo.setAccessibleName(_("Goal calculation"))
        self.target_mode_combo.addItem(_("From work schedule"), "schedule")
        self.target_mode_combo.addItem(_("Custom target"), "manual")
        self.target_mode_combo.setToolTip(_("Automatic goals use planned workdays and daily standard hours. Enabled public holidays follow the selected region."))
        form.addRow(_("Goal calculation"), self.target_mode_combo)
        self.monthly_target_input = _hours_input(0.0, 400.0, 8.0)
        self.monthly_target_input.valueChanged.connect(
            lambda value: actions.set_number(MONTHLY_TARGET_HOURS_SETTING_KEY, value)
        )
        form.addRow(_("Monthly target (h)"), self.monthly_target_input)
        self._target_form = form
        self.target_mode_combo.currentIndexChanged.connect(self._update_target_visibility)
        self.target_mode_combo.currentIndexChanged.connect(
            lambda: actions.set_text(WORK_TARGET_MODE_SETTING_KEY, self.target_mode_combo.currentData()))
        self._update_target_visibility()
        page.layout().addWidget(card)

        card = _card_with_form(_("Recording and reminders"))
        form = card.form_layout

        self.default_break_input = _hours_input(0.0, 4.0, 0.25)
        self.default_break_input.valueChanged.connect(
            lambda value: actions.set_number(DEFAULT_BREAK_HOURS_SETTING_KEY, value)
        )
        form.addRow(_("Default break (h)"), self.default_break_input)

        self.timer_reminder_input = _hours_input(0.0, 16.0, 0.5)
        self.continuous_timer_reminder_input = _hours_input(0.0, 16.0, 0.5)
        for field, caption, key in ((self.timer_reminder_input, _("Long timer reminder (h)"), TIMER_REMINDER_HOURS_SETTING_KEY),
                                    (self.continuous_timer_reminder_input, _("Continuous work timer reminder (h)"), CONTINUOUS_TIMER_REMINDER_HOURS_SETTING_KEY)):
            field.setSpecialValueText(_("Off"))
            field.setKeyboardTracking(False)
            field.setAccessibleName(caption)
            field.valueChanged.connect(lambda value, key=key: actions.set_number(key, value))
            form.addRow(caption, field)

        page.layout().addWidget(card)
        card = _card_with_form(_("Classification"))
        form = card.form_layout

        self.manage_entry_types_button = QPushButton(_("Manage entry types"))
        self.manage_entry_types_button.setObjectName("manage_entry_types_button")
        self.manage_entry_types_button.setFixedWidth(320)
        self.manage_entry_types_button.setProperty("variant", "outline")
        self.manage_entry_types_button.setEnabled(False)
        set_button_icon(self.manage_entry_types_button, "settings")
        self.manage_entry_types_button.clicked.connect(actions.manage_entry_types_requested)
        form.addRow(_("Entry types"), self.manage_entry_types_button)

        self.manage_projects_button = QPushButton(_("Manage projects"))
        self.manage_projects_button.setObjectName("manage_projects_button")
        self.manage_projects_button.setFixedWidth(320)
        self.manage_projects_button.setProperty("variant", "outline")
        self.manage_projects_button.setEnabled(False)
        set_button_icon(self.manage_projects_button, "settings")
        self.manage_projects_button.clicked.connect(actions.manage_projects_requested)
        form.addRow(_("Projects"), self.manage_projects_button)

        page.layout().addWidget(card)
        card = _card_with_form(_("Calendar display"))
        form = card.form_layout

        self.holidays_switch = SwitchButton()
        self.holidays_switch.toggled.connect(
            lambda enabled: actions.set_bool(SHOW_HOLIDAYS_SETTING_KEY, enabled)
        )
        form.addRow(_("Public holidays"), _switch_row(self.holidays_switch))

        self.holiday_country_combo = QComboBox()
        self.holiday_country_combo.setFixedWidth(320)
        self.holiday_country_combo.addItem(
            _("System region") + f" ({system_country or '-'})", ""
        )
        for country in sorted(holiday_regions):
            self.holiday_country_combo.addItem(country, country)
        self.holiday_country_combo.currentIndexChanged.connect(
            actions.holiday_country_changed
        )
        form.addRow(_("Holiday country"), self.holiday_country_combo)
        self.holiday_subdivision_combo = QComboBox()
        self.holiday_subdivision_combo.setFixedWidth(320)
        self.holiday_subdivision_combo.currentIndexChanged.connect(
            actions.holiday_subdivision_changed
        )
        form.addRow(_("State / province"), self.holiday_subdivision_combo)

        self.note_markers_switch = SwitchButton()
        self.note_markers_switch.setVisible(False)
        self.note_markers_switch.toggled.connect(
            lambda enabled: actions.set_bool(SHOW_NOTE_MARKERS_SETTING_KEY, enabled)
        )

        self.overnight_switch = SwitchButton()
        self.overnight_switch.toggled.connect(
            lambda enabled: actions.set_bool(
                SHOW_OVERNIGHT_INDICATOR_SETTING_KEY, enabled
            )
        )
        form.addRow(_("Overnight indicator"), _switch_row(self.overnight_switch))

        self.week_start_switch = SwitchButton()
        self.week_start_switch.toggled.connect(
            lambda enabled: actions.set_bool(WEEK_START_MONDAY_SETTING_KEY, enabled)
        )
        form.addRow(_("Start week on Monday"), _switch_row(self.week_start_switch))
        self.recent_context_switch = SwitchButton()
        self.recent_context_switch.toggled.connect(
            lambda enabled: actions.set_bool(SHOW_RECENT_CONTEXT_SETTING_KEY, enabled)
        )
        form.addRow(_("Show recent context"), _switch_row(self.recent_context_switch))
        page.layout().addWidget(card)

        self.residency_switch: SwitchButton | None = None
        if actions.residency_key:
            card = _card_with_form(_("Application behavior"))
            form = card.form_layout
            self.residency_switch = SwitchButton()
            self.residency_switch.toggled.connect(
                lambda enabled: actions.set_bool(str(actions.residency_key), enabled)
            )
            label = (
                _("Enable tray icon")
                if actions.residency_key == ENABLE_TRAY_SETTING_KEY
                else _("Enable menu bar")
            )
            form.addRow(label, _switch_row(self.residency_switch))
            page.layout().addWidget(card)
        page.layout().addStretch(1)

    def _update_target_visibility(self, *_args):
        self._target_form.setRowVisible(self.monthly_target_input, self.target_mode_combo.currentData() == "manual")
