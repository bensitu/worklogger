"""Presentation ViewModels."""

from worklogger.presentation.viewmodels.auth import AuthModeState, AuthViewModel
from worklogger.presentation.viewmodels.ai_assist import AiAssistViewModel, AiChatState
from worklogger.presentation.viewmodels.analytics import AnalyticsState, AnalyticsViewModel
from worklogger.presentation.viewmodels.auto_record import (
    AutoRecordEntryDraft,
    AutoRecordState,
    AutoRecordViewModel,
)
from worklogger.presentation.viewmodels.calendar import (
    CalendarDayCell,
    CalendarDisplayOptions,
    CalendarMonthViewState,
    CalendarViewModel,
)
from worklogger.presentation.viewmodels.data_management import (
    DataManagementActionState,
    DataManagementViewModel,
)
from worklogger.presentation.viewmodels.local_models import (
    LocalModelManagerState,
    LocalModelManagerViewModel,
)
from worklogger.presentation.viewmodels.identity import (
    IdentityManagementState,
    IdentityManagementViewModel,
)
from worklogger.presentation.viewmodels.notes import NoteEditorState, NoteEditorViewModel
from worklogger.presentation.viewmodels.quick_logs import (
    QuickLogEditorState,
    QuickLogEditorViewModel,
)
from worklogger.presentation.viewmodels.reports import (
    ReportEditorState,
    ReportEditorViewModel,
    ReportHistoryItem,
)
from worklogger.presentation.viewmodels.settings import SettingsState, SettingsViewModel
from worklogger.presentation.viewmodels.stats import StatsPanelState, StatsPanelViewModel
from worklogger.presentation.viewmodels.user_management import (
    UserListItem,
    UserManagementState,
    UserManagementViewModel,
)
from worklogger.presentation.viewmodels.worklog_entry import (
    WorkLogEntryForm,
    WorkLogEntryViewModel,
)

__all__ = [
    "AuthModeState",
    "AuthViewModel",
    "AiAssistViewModel",
    "AiChatState",
    "AnalyticsState",
    "AnalyticsViewModel",
    "AutoRecordEntryDraft",
    "AutoRecordState",
    "AutoRecordViewModel",
    "CalendarDayCell",
    "CalendarDisplayOptions",
    "CalendarMonthViewState",
    "CalendarViewModel",
    "DataManagementActionState",
    "DataManagementViewModel",
    "IdentityManagementState",
    "IdentityManagementViewModel",
    "LocalModelManagerState",
    "LocalModelManagerViewModel",
    "NoteEditorState",
    "NoteEditorViewModel",
    "QuickLogEditorState",
    "QuickLogEditorViewModel",
    "ReportEditorState",
    "ReportEditorViewModel",
    "ReportHistoryItem",
    "SettingsState",
    "SettingsViewModel",
    "StatsPanelState",
    "StatsPanelViewModel",
    "UserListItem",
    "UserManagementState",
    "UserManagementViewModel",
    "WorkLogEntryForm",
    "WorkLogEntryViewModel",
]
