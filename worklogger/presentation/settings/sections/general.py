"""General settings controls."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QPushButton,
)

from worklogger.config.constants import (
    DEFAULT_BREAK_HOURS_SETTING_KEY,
    ENABLE_TRAY_SETTING_KEY,
    MONTHLY_TARGET_HOURS_SETTING_KEY,
    SHOW_HOLIDAYS_SETTING_KEY,
    SHOW_NOTE_MARKERS_SETTING_KEY,
    SHOW_OVERNIGHT_INDICATOR_SETTING_KEY,
    STANDARD_WORK_HOURS_SETTING_KEY,
    WEEK_START_MONDAY_SETTING_KEY,
)
from worklogger.infrastructure.calendar.holidays_provider import (
    detect_country,
    supported_holiday_regions,
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


class GeneralSection(_SettingsScrollPage):
    control_names = (
        "default_break_input",
        "holiday_country_combo",
        "holiday_subdivision_combo",
        "holidays_switch",
        "monthly_target_input",
        "note_markers_switch",
        "overnight_switch",
        "residency_switch",
        "standard_hours_input",
        "week_start_switch",
        "manage_work_types_button",
    )

    def __init__(self, actions: SectionActions):
        super().__init__()
        page = self
        card = _card_with_form(_("General"))
        form = card.form_layout

        self.standard_hours_input = _hours_input(1.0, 24.0, 0.5)
        self.standard_hours_input.valueChanged.connect(
            lambda value: actions.set_number(STANDARD_WORK_HOURS_SETTING_KEY, value)
        )
        form.addRow(_("Standard hours (h)"), self.standard_hours_input)

        self.default_break_input = _hours_input(0.0, 4.0, 0.25)
        self.default_break_input.valueChanged.connect(
            lambda value: actions.set_number(DEFAULT_BREAK_HOURS_SETTING_KEY, value)
        )
        form.addRow(_("Default break (h)"), self.default_break_input)

        self.monthly_target_input = _hours_input(0.0, 400.0, 8.0)
        self.monthly_target_input.valueChanged.connect(
            lambda value: actions.set_number(MONTHLY_TARGET_HOURS_SETTING_KEY, value)
        )
        form.addRow(_("Monthly target (h)"), self.monthly_target_input)

        self.manage_work_types_button = QPushButton(_("Manage work types"))
        self.manage_work_types_button.setObjectName("manage_work_types_button")
        self.manage_work_types_button.setFixedWidth(320)
        self.manage_work_types_button.setProperty("variant", "outline")
        self.manage_work_types_button.setEnabled(False)
        set_button_icon(self.manage_work_types_button, "settings", accent=True)
        self.manage_work_types_button.clicked.connect(actions.manage_work_types_requested)
        form.addRow(_("Work types"), self.manage_work_types_button)

        self.holidays_switch = SwitchButton()
        self.holidays_switch.toggled.connect(
            lambda enabled: actions.set_bool(SHOW_HOLIDAYS_SETTING_KEY, enabled)
        )
        form.addRow(_("Public holidays"), _switch_row(self.holidays_switch))

        self.holiday_country_combo = QComboBox()
        self.holiday_country_combo.setFixedWidth(320)
        self.holiday_country_combo.addItem(
            _("System region") + f" ({detect_country() or '-'})", ""
        )
        for country in sorted(supported_holiday_regions()):
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

        self.residency_switch: SwitchButton | None = None
        if actions.residency_key:
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
