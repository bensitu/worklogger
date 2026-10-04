"""Select a compatible base style before applying application stylesheets."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication


def configure_application_style() -> None:
    application = QApplication.instance()
    if application is None or sys.platform != "win32":
        return
    # Windows 11 menu rendering assumes point-sized fonts, including combo popups.
    if application.style().objectName().lower() == "windows11":
        application.setStyle("Fusion")
