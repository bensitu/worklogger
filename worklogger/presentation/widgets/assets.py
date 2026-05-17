"""Qt asset loading helpers."""

from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QWidget


ASSETS_ROOT = Path(__file__).resolve().parents[2] / "assets"


def asset_path(relative_path: str | Path) -> Path:
    return ASSETS_ROOT / Path(relative_path)


def pixmap_asset(relative_path: str | Path) -> QPixmap:
    return QPixmap(str(asset_path(relative_path)))


def application_icon_path(platform: str | None = None) -> Path:
    platform_name = platform or sys.platform
    if platform_name.startswith("win"):
        return asset_path(Path("icons") / "worklogger.ico")
    if platform_name == "darwin":
        return asset_path(Path("icons") / "worklogger.icns")
    return asset_path(Path("icons") / "worklogger.webp")


def application_icon(platform: str | None = None) -> QIcon:
    return QIcon(str(application_icon_path(platform)))


def apply_application_icon() -> None:
    application = QApplication.instance()
    if application is not None:
        application.setWindowIcon(application_icon())


def apply_window_icon(widget: QWidget) -> None:
    widget.setWindowIcon(application_icon())
