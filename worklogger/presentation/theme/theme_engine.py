"""Public Qt theme facade backed by shared definitions and material profiles."""

from PySide6.QtGui import QColor, QPalette

from worklogger.config.themes import THEME_CATALOG, normalize_theme
from worklogger.domain.settings.appearance import DEFAULT_CUSTOM_COLOR as DEFAULT_CUSTOM_COLOR, THEME_KEYS as THEME_KEYS, normalize_hex_color
from worklogger.domain.worklog.models import CustomWorkType, WorkType
from worklogger.presentation.theme import calendar_styles
from worklogger.presentation.theme.models import CalendarCellStyle, ColorPalette
from worklogger.presentation.theme.palettes import build_palette
from worklogger.presentation.theme.stylesheets import application_stylesheet as render_stylesheet


class ThemeEngine:
    def palette(
        self,
        theme: str = "blue",
        *,
        dark: bool = False,
        custom_color: str | None = None,
    ) -> ColorPalette:
        definition = THEME_CATALOG[normalize_theme(theme)]
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

    def work_type_marker_color(
        self,
        work_type: WorkType | CustomWorkType | str,
        *,
        dark: bool = False,
    ) -> str | None:
        return calendar_styles.work_type_marker_color(work_type, dark=dark)

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
        palette = self.palette(theme, dark=dark, custom_color=custom_color)
        qt_palette = QPalette()

        _set_palette_color(qt_palette, QPalette.ColorRole.Window, palette.background)
        _set_palette_color(qt_palette, QPalette.ColorRole.WindowText, palette.text)
        _set_palette_color(qt_palette, QPalette.ColorRole.Base, palette.input_background)
        _set_palette_color(qt_palette, QPalette.ColorRole.AlternateBase, palette.table_alternate)
        _set_palette_color(qt_palette, QPalette.ColorRole.Text, palette.text)
        _set_palette_color(qt_palette, QPalette.ColorRole.Button, palette.surface)
        _set_palette_color(qt_palette, QPalette.ColorRole.ButtonText, palette.text)
        _set_palette_color(qt_palette, QPalette.ColorRole.Highlight, palette.accent)
        _set_palette_color(qt_palette, QPalette.ColorRole.HighlightedText, palette.highlighted_text)
        _set_palette_color(qt_palette, QPalette.ColorRole.Link, palette.accent)
        qt_palette.setColor(
            QPalette.ColorGroup.Disabled,
            QPalette.ColorRole.WindowText,
            QColor(palette.disabled_text),
        )
        qt_palette.setColor(
            QPalette.ColorGroup.Disabled,
            QPalette.ColorRole.Text,
            QColor(palette.disabled_text),
        )
        qt_palette.setColor(
            QPalette.ColorGroup.Disabled,
            QPalette.ColorRole.ButtonText,
            QColor(palette.disabled_text),
        )
        return qt_palette


def contrasting_text_color(background: QColor) -> QColor:
    def linear(channel):
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
    luminance = sum(weight * linear(channel) for weight, channel in zip(
        (0.2126, 0.7152, 0.0722), (background.redF(), background.greenF(), background.blueF())))
    return QColor("#000000" if luminance > 0.179 else "#ffffff")


def _set_palette_color(qt_palette: QPalette, role: QPalette.ColorRole, color: str) -> None:
    qt_palette.setColor(role, QColor(color))
