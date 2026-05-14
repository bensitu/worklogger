"""Presentation shell components."""

from worklogger.presentation.shell.app_window import AppWindow, AppWindowConfig
from worklogger.presentation.shell.minimal_view import MinimalView, MinimalViewConfig
from worklogger.presentation.shell.residency import (
    QtResidencyController,
    ResidencyState,
    ResidencyViewModel,
    residency_setting_key,
)

__all__ = [
    "AppWindow",
    "AppWindowConfig",
    "MinimalView",
    "MinimalViewConfig",
    "QtResidencyController",
    "ResidencyState",
    "ResidencyViewModel",
    "residency_setting_key",
]
