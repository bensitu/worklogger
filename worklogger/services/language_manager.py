from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEvent
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from config.constants import (
    DEFAULT_LANGUAGE_FONT,
    DEFAULT_UI_FONT_POINT_SIZE,
    LANGUAGE_FONT_FILES,
)
from utils.i18n import set_language
from utils.paths import font_path


@dataclass(frozen=True)
class LanguageApplyResult:
    language: str
    font_family: str | None
    font_path: str | None


class LanguageManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._loaded_font_families: dict[str, str] = {}
        self._current = LanguageApplyResult("en_US", None, None)

    @property
    def current(self) -> LanguageApplyResult:
        return self._current

    def apply(self, lang: str | None) -> LanguageApplyResult:
        with self._lock:
            normalized = set_language(lang)
            primary_font_path = self.font_path_for(normalized)
            font_family = self._load_font_family(primary_font_path)
            fallback_family = self._load_font_family(font_path(DEFAULT_LANGUAGE_FONT))
            self._apply_qt_font(font_family, fallback_family)
            self._current = LanguageApplyResult(
                normalized,
                font_family,
                str(primary_font_path) if primary_font_path else None,
            )
            return self._current

    def font_path_for(self, lang: str | None) -> Path | None:
        filename = LANGUAGE_FONT_FILES.get(str(lang), DEFAULT_LANGUAGE_FONT)
        path = font_path(filename)
        if path is not None:
            return path
        if filename != DEFAULT_LANGUAGE_FONT:
            return font_path(DEFAULT_LANGUAGE_FONT)
        return None

    def _load_font_family(self, font_path: Path | None) -> str | None:
        if font_path is None:
            return None
        key = os.path.normcase(str(font_path.resolve(strict=False)))
        family = self._loaded_font_families.get(key)
        if family:
            return family

        font_id = QFontDatabase.addApplicationFont(str(font_path))
        if font_id < 0:
            return None
        families = QFontDatabase.applicationFontFamilies(font_id)
        if not families:
            return None
        family = families[0]
        self._loaded_font_families[key] = family
        return family

    def _apply_qt_font(
        self,
        font_family: str | None,
        fallback_family: str | None = None,
    ) -> None:
        app = QApplication.instance()
        if app is None or not font_family:
            return
        current = app.font()
        font = QFont(font_family)
        families = [font_family]
        if fallback_family and fallback_family != font_family:
            families.append(fallback_family)
        if families and hasattr(font, "setFamilies"):
            font.setFamilies(families)
        if current.pointSizeF() > 0:
            font.setPointSizeF(current.pointSizeF())
        elif current.pointSize() > 0:
            font.setPointSize(current.pointSize())
        else:
            font.setPointSize(DEFAULT_UI_FONT_POINT_SIZE)
        app.setFont(font)
        for window in app.topLevelWidgets():
            QApplication.sendEvent(window, QEvent(QEvent.Type.FontChange))


_language_manager: LanguageManager | None = None
_language_manager_lock = threading.Lock()


def get_language_manager() -> LanguageManager:
    global _language_manager
    with _language_manager_lock:
        if _language_manager is None:
            _language_manager = LanguageManager()
        return _language_manager
