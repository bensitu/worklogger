"""Qt palette adaptation with bounded caching and independent returned values."""

from functools import lru_cache

from PySide6.QtGui import QColor, QPalette

from worklogger.presentation.theme.models import ColorPalette


@lru_cache(maxsize=32)
def _build_palette(colors: ColorPalette) -> QPalette:
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: colors.background,
        QPalette.ColorRole.WindowText: colors.text,
        QPalette.ColorRole.Base: colors.input_background,
        QPalette.ColorRole.AlternateBase: colors.table_alternate,
        QPalette.ColorRole.Text: colors.text,
        QPalette.ColorRole.Button: colors.surface,
        QPalette.ColorRole.ButtonText: colors.text,
        QPalette.ColorRole.Highlight: colors.accent,
        QPalette.ColorRole.HighlightedText: colors.highlighted_text,
        QPalette.ColorRole.Link: colors.accent,
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(colors.disabled_text))
    return palette


def qt_palette(colors: ColorPalette) -> QPalette:
    return QPalette(_build_palette(colors))
