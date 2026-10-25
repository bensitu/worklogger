"""Opt-in settings layout coverage for translated captions and theme materials."""

import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QPoint
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from tests.presentation.test_settings_presentation import MemorySettingsRepository, _view_model
from worklogger.domain.auth.models import User
from worklogger.domain.cloud_backup import BackupConfiguration, BackupCredentials
from worklogger.infrastructure.i18n import available_languages, get_language, set_language
from worklogger.presentation.settings import SettingsPage
from worklogger.presentation.settings.sections.layouts import SettingsContainer
from worklogger.presentation.settings_capabilities import SettingsCapabilities
from worklogger.presentation.theme import ThemeEngine, configure_application_style, install_bundled_fonts


class SettingsLayoutChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        configure_application_style()
        install_bundled_fonts()

    def test_settings_fit_supported_locales_materials_and_screen_widths(self):
        old_language = get_language()
        old_palette, old_style = self.app.palette(), self.app.styleSheet()
        old_context = self.app.property("worklogger_theme_context")
        try:
            for language in available_languages():
                set_language(language)
                for theme in ("blue", "liquid_glass"):
                    for dark in (False, True):
                        ThemeEngine().apply_to(self.app, theme, dark=dark)
                        repository = MemorySettingsRepository()
                        repository.set(1, "language", language)
                        repository.set(1, "network_proxy_enabled", "1")
                        page = SettingsPage(_view_model(repository))
                        self.assertTrue(page.refresh())
                        page.set_account(User(1, "sample-user", is_admin=True, display_name="Sample User"))
                        page.set_capabilities(SettingsCapabilities(external_generation=True, local_generation=True,
                            proxy_routing=True, minimal_view=True))
                        page.cloud_backup_panel.set_configuration(BackupConfiguration(provider="s3", schedule="monthly"), BackupCredentials())
                        page.cloud_backup_panel.set_busy(False, configured=True)
                        page.background_settings.show()
                        page.background_settings.options_widget.show()
                        page.show()
                        try:
                            for width in (620, 900, 1200):
                                page.resize(width, 760)
                                for category in page._category_pages:
                                    page.category_nav.set_category(category)
                                    self.process_layout()
                                    context = language, theme, dark, width, category
                                    self.check_page(page, context)
                                    self.capture(page.category_stack.currentWidget().content_widget,
                                        f"{language}-{theme}-{dark}-{width}-{category}")
                            page.set_capabilities(SettingsCapabilities(ai_enabled=False, cloud_backup_enabled=False, oidc_enabled=False))
                            for category in ("ai", "data", "account"):
                                page.category_nav.set_category(category)
                                self.process_layout()
                                self.check_page(page, (language, theme, dark, "disabled", category))
                        finally:
                            page.close()
                            page.deleteLater()
                            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        finally:
            set_language(old_language)
            self.app.setPalette(old_palette)
            self.app.setStyleSheet(old_style)
            self.app.setProperty("worklogger_theme_context", old_context)

    def process_layout(self):
        for _pass in range(5):
            self.app.processEvents()

    def check_page(self, page, context):
        scroll = page.category_stack.currentWidget()
        self.assertEqual(scroll.horizontalScrollBar().maximum(), 0, context)
        content = scroll.content_widget
        for button in content.findChildren(QPushButton):
            if button.isVisible():
                bounds = button.rect().translated(button.mapTo(content, QPoint()))
                self.assertTrue(content.rect().contains(bounds), (context, button.text()))
                self.assertGreaterEqual(button.width(), button.minimumSizeHint().width(), (context, button.text()))
        for label in content.findChildren(QLabel, "settings_section_title_label"):
            if label.isVisible():
                self.assertTrue(label.parentWidget().rect().contains(label.geometry()), context)
                self.assertGreaterEqual(label.height() + 1, label.heightForWidth(label.width()), (context, label.text()))
        for container in content.findChildren(SettingsContainer):
            if container.isVisible():
                self.assertEqual(container.palette().color(container.backgroundRole()).alpha(), 0, (context, container.objectName()))

    def capture(self, widget, name):
        directory = os.environ.get("WORKLOGGER_SCREENSHOTS")
        if directory:
            target = Path(directory)
            target.mkdir(parents=True, exist_ok=True)
            self.assertTrue(widget.grab().save(str(target / f"{name}.png")))
