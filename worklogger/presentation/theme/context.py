"""Resolved colors for custom painting without inspecting widget backgrounds."""

from dataclasses import replace

from PySide6.QtGui import QGuiApplication, QPalette

from worklogger.presentation.theme.models import ColorPalette

_CONTEXT_PROPERTY = "worklogger_theme_context"


def remember_colors(application, colors: ColorPalette) -> None:
    application.setProperty(_CONTEXT_PROPERTY, (colors, application.palette()))


def current_colors() -> ColorPalette:
    application = QGuiApplication.instance()
    palette = QGuiApplication.palette()
    context = application.property(_CONTEXT_PROPERTY) if application is not None else None
    if (isinstance(context, tuple) and len(context) == 2
            and isinstance(context[0], ColorPalette) and context[1] == palette):
        return context[0]

    from worklogger.presentation.theme.theme_engine import ThemeEngine
    accent = palette.color(QPalette.ColorRole.Highlight).name()
    colors = ThemeEngine().palette("custom", dark=palette.color(QPalette.ColorRole.Window).lightness() < 128,
                                   custom_color=accent)
    return replace(colors, accent=accent, text=palette.color(QPalette.ColorRole.WindowText).name())
