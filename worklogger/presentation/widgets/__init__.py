"""Qt widgets for presentation views."""

from worklogger.presentation.widgets.card import CardFrame
from worklogger.presentation.widgets.calendar import CalendarDayButton, CalendarView
from worklogger.presentation.widgets.combo_chart import ComboChart
from worklogger.presentation.widgets.export_menu_button import ExportMenuButton
from worklogger.presentation.widgets.icon_line_edit import IconLineEdit
from worklogger.presentation.widgets.page_header import PageHeader
from worklogger.presentation.widgets.progress_cards import (
    DonutProgressCard,
    DotProgressCard,
)
from worklogger.presentation.widgets.report_history import (
    ReportHistoryDisplayItem,
    ReportHistoryPanel,
)
from worklogger.presentation.widgets.segmented_control import SegmentedControl
from worklogger.presentation.widgets.settings_nav import SettingsNav
from worklogger.presentation.widgets.sidebar import SidebarWidget
from worklogger.presentation.widgets.stats import StatsPanel
from worklogger.presentation.widgets.switch_button import SwitchButton
from worklogger.presentation.widgets.worklog_entry import (
    WorkLogEntryDraft,
    WorkLogEntryPanel,
)

__all__ = [
    "CardFrame",
    "CalendarDayButton",
    "CalendarView",
    "ComboChart",
    "DonutProgressCard",
    "DotProgressCard",
    "ExportMenuButton",
    "IconLineEdit",
    "PageHeader",
    "ReportHistoryDisplayItem",
    "ReportHistoryPanel",
    "SegmentedControl",
    "SettingsNav",
    "SidebarWidget",
    "StatsPanel",
    "SwitchButton",
    "WorkLogEntryDraft",
    "WorkLogEntryPanel",
]
