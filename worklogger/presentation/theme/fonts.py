"""Application font loading."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication


_FONT_ROOT = Path(__file__).resolve().parents[2] / "assets" / "fonts"
_FONT_FILES = (
    "NotoSans-Regular.otf",
    "NotoSansJP-Regular.otf",
    "NotoSansKR-Regular.otf",
    "NotoSansSC-Regular.otf",
    "NotoSansTC-Regular.otf",
)
_INSTALLED = False


def install_bundled_fonts() -> None:
    global _INSTALLED
    application = QApplication.instance()
    if application is None:
        return
    if not _INSTALLED:
        primary_family = ""
        for filename in _FONT_FILES:
            font_id = QFontDatabase.addApplicationFont(str(_FONT_ROOT / filename))
            if font_id >= 0 and not primary_family:
                families = QFontDatabase.applicationFontFamilies(font_id)
                primary_family = families[0] if families else ""
        if primary_family:
            application.setFont(QFont(primary_family, 10))
        _INSTALLED = True

