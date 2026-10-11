"""Shared window appearance lifecycle without business or navigation state."""

from PySide6.QtCore import QObject, Slot
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from worklogger.presentation.shell.background_controller import BackgroundController
from worklogger.presentation.theme import ThemeEngine, configure_application_style, install_bundled_fonts
from worklogger.presentation.theme.glass_surfaces import GlassThemeController
from worklogger.presentation.theme.widget_style import refresh_style_tree


class WindowAppearanceController(QObject):
    def __init__(self, window, surface, *, theme_engine=None, background_service=None,
                 background_images_available=False, job_runner=None):
        super().__init__(window)
        self._surface = surface
        self._theme_engine = theme_engine or ThemeEngine()
        self._disposed = False
        self.background = BackgroundController(surface, background_service,
            available=background_images_available, job_runner=job_runner)
        self.glass = GlassThemeController(window, surface, job_runner=job_runner)
        surface.active_changed.connect(self._refresh_background_styles)
        window.destroyed.connect(self.dispose)

    def apply(self, theme, *, dark=False, custom_color=None, force=False):
        if self._disposed:
            return None
        application = QApplication.instance()
        configure_application_style()
        install_bundled_fonts()
        colors = self._theme_engine.apply_to(application, theme, dark=dark,
                                             custom_color=custom_color, force=force)
        self._surface.set_base_color(colors.surface)
        self.glass.configure(colors)
        return colors

    @Slot(bool)
    def _refresh_background_styles(self, _active):
        if not self._disposed:
            refresh_style_tree(self._surface)

    @Slot()
    def dispose(self):
        if self._disposed:
            return
        self._disposed = True
        self.background.dispose()
        self.glass.dispose()
        if isValid(self._surface):
            self._surface.shutdown()
