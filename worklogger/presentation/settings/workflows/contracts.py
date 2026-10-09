"""Settings presentation callback contracts."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import QWidget

from worklogger.presentation.settings.dialog import SettingsDialog
from worklogger.presentation.settings.page import SettingsPage
from worklogger.presentation.user_management import UserManagementDialog
from worklogger.presentation.viewmodels import (
    SettingsViewModel,
    UserManagementViewModel,
)

SettingsDialogFactory = Callable[[SettingsViewModel, QWidget | None], SettingsDialog]

SettingsPageFactory = Callable[[SettingsViewModel, QWidget | None], SettingsPage]

UserManagementDialogFactory = Callable[
    [UserManagementViewModel, QWidget | None],
    UserManagementDialog,
]

PathProvider = Callable[[QWidget | None], Path | None]

ConfirmationProvider = Callable[[QWidget | None], bool]

IcsImportModeProvider = Callable[[QWidget | None], bool | None]

NotificationHandler = Callable[[QWidget | None, str, str], None]

ReloadHandler = Callable[[], bool | None]
