"""Public Qt theme facade backed by shared definitions and material profiles."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtGui import QColor, QPalette

from worklogger.config.themes import get_theme
from worklogger.domain.settings.appearance import DEFAULT_CUSTOM_COLOR as DEFAULT_CUSTOM_COLOR, THEME_KEYS as THEME_KEYS, normalize_hex_color
from worklogger.domain.worklog.models import CustomEntryType, EntryType
from worklogger.presentation.theme import calendar_styles
from worklogger.presentation.theme.models import CalendarCellStyle, ColorPalette
from worklogger.presentation.theme.palettes import build_palette
from worklogger.presentation.theme.stylesheets import application_stylesheet as render_stylesheet


class ThemeEngine:
    def apply_to(self, application, theme: str = "blue", *, dark: bool = False,
                 custom_color: str | None = None, force: bool = False) -> ColorPalette:
        from worklogger.presentation.theme.context import remember_colors
        colors = self.palette(theme, dark=dark, custom_color=custom_color)
        palette = self.qt_palette(theme, dark=dark, custom_color=custom_color)
        stylesheet = render_stylesheet(colors)
        if application.palette() != palette:
            application.setPalette(palette)
        if force or application.styleSheet() != stylesheet:
            application.setStyleSheet(stylesheet)
        remember_colors(application, colors)
        return colors

    def palette(
        self,
        theme: str = "blue",
        *,
        dark: bool = False,
        custom_color: str | None = None,
    ) -> ColorPalette:
        definition = get_theme(theme)
        accent = normalize_hex_color(custom_color) if definition.customizable else None
        return build_palette(definition, bool(dark), accent)

    def calendar_cell_style(
        self,
        flags: set[str],
        *,
        theme: str = "blue",
        dark: bool = False,
        custom_color: str | None = None,
    ) -> CalendarCellStyle:
        palette = self.palette(theme, dark=dark, custom_color=custom_color)
        return calendar_styles.calendar_cell_style(flags, palette)

    def entry_type_color(
        self,
        entry_type: EntryType | CustomEntryType | str,
        *,
        dark: bool = False,
    ) -> str | None:
        return calendar_styles.entry_type_color(entry_type, dark=dark)

    def application_stylesheet(
        self,
        theme: str = "blue",
        *,
        dark: bool = False,
        custom_color: str | None = None,
    ) -> str:
        return render_stylesheet(self.palette(theme, dark=dark, custom_color=custom_color))

    def qt_palette(
        self,
        theme: str = "blue",
        *,
        dark: bool = False,
        custom_color: str | None = None,
    ) -> QPalette:
        from worklogger.presentation.theme.qt_palette import qt_palette
        return qt_palette(self.palette(theme, dark=dark, custom_color=custom_color))


def contrasting_text_color(background: QColor) -> QColor:
    from PySide6.QtGui import QColor
    from worklogger.presentation.theme.color_contrast import contrasting_foreground
    return QColor(contrasting_foreground(background.name()))
