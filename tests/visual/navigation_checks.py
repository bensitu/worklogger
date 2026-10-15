"""Opt-in rendering checks for application and settings navigation states."""

import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QHBoxLayout, QStyle, QStyleOptionButton, QWidget

from worklogger.presentation.theme import ThemeEngine, configure_application_style, install_bundled_fonts
from worklogger.presentation.widgets.settings_nav import SettingsNav
from worklogger.presentation.widgets.sidebar import SidebarWidget


class NavigationLayoutChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        configure_application_style()
        install_bundled_fonts()

    def test_navigation_hover_preserves_active_and_disabled_states(self):
        old_style, old_palette = self.app.styleSheet(), self.app.palette()
        old_context = self.app.property("worklogger_theme_context")
        engine = ThemeEngine()
        try:
            for theme in ("blue", "liquid_glass"):
                for dark in (False, True):
                    colors = engine.apply_to(self.app, theme, dark=dark)
                    window = QWidget()
                    layout = QHBoxLayout(window)
                    sidebar = SidebarWidget(account_name="Sample User")
                    settings = SettingsNav((("appearance", "Appearance"), ("general", "General")))
                    layout.addWidget(sidebar)
                    layout.addWidget(settings)
                    window.resize(420, 560)
                    window.show()
                    self.app.processEvents()
                    try:
                        for navigation, button in ((sidebar, sidebar.button("analytics")),
                                                   (settings, settings._buttons["general"])):
                            for active in (False, True):
                                if navigation is sidebar:
                                    sidebar.set_active_route("analytics" if active else "calendar")
                                else:
                                    settings.set_category("general" if active else "appearance")
                                self.app.processEvents()
                                before = self.render_button(button, hovered=False)
                                geometry, weight = button.geometry(), button.font().weight()
                                self.assertNotEqual(before, self.render_button(button, hovered=True),
                                                    (theme, dark, active, button.objectName()))
                                self.assertEqual((button.geometry(), button.font().weight()), (geometry, weight))
                                self.assertEqual(button.palette().color(button.foregroundRole()).name(),
                                                 colors.accent if active else colors.text)
                                button.setEnabled(False)
                                disabled = self.render_button(button, hovered=False)
                                self.assertEqual(disabled, self.render_button(button, hovered=True))
                                button.setEnabled(True)
                        destination = os.environ.get("WORKLOGGER_SCREENSHOTS")
                        if destination:
                            path = Path(destination)
                            path.mkdir(parents=True, exist_ok=True)
                            self.assertTrue(window.grab().save(str(path / f"{theme}-navigation-{dark}.png")))
                    finally:
                        window.close()
                        window.deleteLater()
        finally:
            self.app.setStyleSheet(old_style)
            self.app.setPalette(old_palette)
            self.app.setProperty("worklogger_theme_context", old_context)

    def render_button(self, button, *, hovered):
        option = QStyleOptionButton()
        button.initStyleOption(option)
        if hovered:
            option.state |= QStyle.StateFlag.State_MouseOver
        else:
            option.state &= ~QStyle.StateFlag.State_MouseOver
        image = QImage(button.size(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        try:
            button.style().drawControl(QStyle.ControlElement.CE_PushButton, option, painter, button)
        finally:
            painter.end()
        return image
