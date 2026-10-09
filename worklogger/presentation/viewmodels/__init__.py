"""Public view-model types loaded only when requested by a consumer."""

from importlib import import_module

_EXPORTS = {
    "WorkTypeManagerViewModel": ["worklogger.presentation.viewmodels.work_types", "WorkTypeManagerViewModel"],
    "AuthModeState": [
        "worklogger.presentation.viewmodels.auth",
        "AuthModeState"
    ],
    "AuthViewModel": [
        "worklogger.presentation.viewmodels.auth",
        "AuthViewModel"
    ],
    "AiAssistViewModel": [
        "worklogger.presentation.viewmodels.ai_assist",
        "AiAssistViewModel"
    ],
    "AiChatState": [
        "worklogger.presentation.viewmodels.ai_assist",
        "AiChatState"
    ],
    "AnalyticsState": [
        "worklogger.presentation.viewmodels.analytics",
        "AnalyticsState"
    ],
    "AnalyticsViewModel": [
        "worklogger.presentation.viewmodels.analytics",
        "AnalyticsViewModel"
    ],
    "CalendarDayCell": [
        "worklogger.presentation.viewmodels.calendar",
        "CalendarDayCell"
    ],
    "CalendarDisplayOptions": [
        "worklogger.presentation.viewmodels.calendar",
        "CalendarDisplayOptions"
    ],
    "CalendarMonthViewState": [
        "worklogger.presentation.viewmodels.calendar",
        "CalendarMonthViewState"
    ],
    "CalendarViewModel": [
        "worklogger.presentation.viewmodels.calendar",
        "CalendarViewModel"
    ],
    "DataManagementActionState": [
        "worklogger.presentation.viewmodels.data_management",
        "DataManagementActionState"
    ],
    "DataManagementViewModel": [
        "worklogger.presentation.viewmodels.data_management",
        "DataManagementViewModel"
    ],
    "LocalModelManagerState": [
        "worklogger.presentation.viewmodels.local_models",
        "LocalModelManagerState"
    ],
    "LocalModelManagerViewModel": [
        "worklogger.presentation.viewmodels.local_models",
        "LocalModelManagerViewModel"
    ],
    "IdentityManagementState": [
        "worklogger.presentation.viewmodels.identity",
        "IdentityManagementState"
    ],
    "IdentityManagementViewModel": [
        "worklogger.presentation.viewmodels.identity",
        "IdentityManagementViewModel"
    ],
    "NoteEditorState": [
        "worklogger.presentation.viewmodels.notes",
        "NoteEditorState"
    ],
    "NoteEditorViewModel": [
        "worklogger.presentation.viewmodels.notes",
        "NoteEditorViewModel"
    ],
    "QuickLogEditorState": [
        "worklogger.presentation.viewmodels.quick_logs",
        "QuickLogEditorState"
    ],
    "QuickLogEditorViewModel": [
        "worklogger.presentation.viewmodels.quick_logs",
        "QuickLogEditorViewModel"
    ],
    "ReportEditorState": [
        "worklogger.presentation.viewmodels.reports",
        "ReportEditorState"
    ],
    "ReportEditorViewModel": [
        "worklogger.presentation.viewmodels.reports",
        "ReportEditorViewModel"
    ],
    "ReportHistoryItem": [
        "worklogger.presentation.viewmodels.reports",
        "ReportHistoryItem"
    ],
    "SettingsState": [
        "worklogger.presentation.viewmodels.settings",
        "SettingsState"
    ],
    "SettingsViewModel": [
        "worklogger.presentation.viewmodels.settings",
        "SettingsViewModel"
    ],
    "StatsPanelState": [
        "worklogger.presentation.viewmodels.stats",
        "StatsPanelState"
    ],
    "StatsPanelViewModel": [
        "worklogger.presentation.viewmodels.stats",
        "StatsPanelViewModel"
    ],
    "UserListItem": [
        "worklogger.presentation.viewmodels.user_management",
        "UserListItem"
    ],
    "UserManagementState": [
        "worklogger.presentation.viewmodels.user_management",
        "UserManagementState"
    ],
    "UserManagementViewModel": [
        "worklogger.presentation.viewmodels.user_management",
        "UserManagementViewModel"
    ],
    "TimeEntryDraft": [
        "worklogger.presentation.viewmodels.time_entries",
        "TimeEntryDraft"
    ],
    "TimeEntryViewModel": [
        "worklogger.presentation.viewmodels.time_entries",
        "TimeEntryViewModel"
    ]
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, attribute = _EXPORTS[name]
    value = getattr(import_module(module), attribute)
    globals()[name] = value
    return value
