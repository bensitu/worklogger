"""Opt-in cloud backup configuration and confirmation layout checks."""

import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QPoint
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QScrollArea, QStyle, QStyleOptionComboBox

from worklogger.domain.cloud_backup import BackupConfiguration, BackupCredentials, BackupOverview, BackupVersion
from worklogger.infrastructure.i18n import available_languages, get_language, set_language
from worklogger.presentation.settings.sections.cloud_backup import CloudBackupPanel
from worklogger.presentation.settings.workflows.cloud_backup import BackupTransferDialog
from worklogger.presentation.theme import ThemeEngine, configure_application_style, install_bundled_fonts


class CloudBackupLayoutChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        configure_application_style()
        install_bundled_fonts()

    def test_provider_forms_and_restore_confirmations_fit_supported_locales_and_themes(self):
        old_language = get_language()
        old_palette, old_style = self.app.palette(), self.app.styleSheet()
        old_context = self.app.property("worklogger_theme_context")
        try:
            for language in available_languages():
                set_language(language)
                for dark in (False, True):
                    ThemeEngine().apply_to(self.app, "green", dark=dark)
                    for provider in ("webdav", "s3"):
                        for width in (520, 900):
                            scroll = QScrollArea()
                            scroll.setWidgetResizable(True)
                            panel = CloudBackupPanel()
                            scroll.setWidget(panel)
                            panel.set_configuration(BackupConfiguration(provider=provider, endpoint="https://storage.example",
                                bucket="personal-backups", schedule="weekly"),
                                BackupCredentials("synthetic-user", "synthetic-password", "synthetic-token", "synthetic-passphrase"))
                            panel.set_busy(False, configured=True)
                            scroll.resize(width, 640)
                            scroll.show()
                            try:
                                for _pass in range(4):
                                    self.app.processEvents()
                                self.assertEqual(scroll.horizontalScrollBar().maximum(), 0, (language, dark, provider, width))
                                for schedule in ("off", "interval", "daily", "weekly", "monthly"):
                                    panel.schedule.setCurrentIndex(panel.schedule.findData(schedule))
                                    for _pass in range(4):
                                        self.app.processEvents()
                                    self.check_fields(panel, width)
                                self.capture(panel, f"{language}-{'dark' if dark else 'light'}-{provider}-{width}-monthly")
                                for widget in (panel.endpoint, panel.password, panel.time, panel.weekday,
                                               panel.save_button, panel.restore_button, panel.local_restore_button):
                                    self.assertTrue(panel.rect().contains(widget.rect().translated(widget.mapTo(panel, QPoint()))))
                                self.capture(scroll, f"{language}-{'dark' if dark else 'light'}-{provider}-{width}")
                                panel.encrypted.setChecked(False)
                                for _pass in range(4):
                                    self.app.processEvents()
                                self.check_fields(panel, width)
                                self.assertFalse(panel.passphrase.isVisible())
                                self.capture(panel, f"{language}-{'dark' if dark else 'light'}-{provider}-{width}-unencrypted")
                            finally:
                                scroll.hide()
                                scroll.deleteLater()
                                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                    version = BackupVersion("a" * 32, "2026-10-18T10:00:00+00:00", "b" * 64, 100, True)
                    overview = BackupOverview((version,), "digest", True, True)
                    for local in (False, True):
                        dialog = BackupTransferDialog(overview, restore=True, local_path="personal-recovery.wlbackup" if local else None)
                        try:
                            dialog.show()
                            self.app.processEvents()
                            self.assertTrue(dialog.force.isVisible())
                            buttons = dialog.findChild(QDialogButtonBox)
                            self.assertFalse(buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled())
                            dialog.force.setChecked(True)
                            self.assertTrue(buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled())
                            for field in (dialog.force, dialog.passphrase, buttons):
                                self.assertTrue(dialog.rect().contains(field.rect().translated(field.mapTo(dialog, QPoint()))))
                            self.capture(dialog, f"{language}-{'dark' if dark else 'light'}-{'local' if local else 'cloud'}-restore")
                        finally:
                            dialog.hide()
                            dialog.deleteLater()
                            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        finally:
            set_language(old_language)
            self.app.setPalette(old_palette)
            self.app.setStyleSheet(old_style)
            self.app.setProperty("worklogger_theme_context", old_context)

    def check_fields(self, panel, width):
        bounds = []
        for label, field in panel._rows.values():
            if field.isVisible():
                for control in (label, field) if label is not None else (field,):
                    rectangle = control.rect().translated(control.mapTo(panel, QPoint()))
                    if not rectangle.isEmpty():
                        self.assertTrue(panel.rect().contains(rectangle), control.accessibleName())
                        self.assertFalse(any(rectangle.intersects(other) for other in bounds), control.accessibleName())
                        bounds.append(rectangle)
        option = QStyleOptionComboBox()
        panel.schedule.initStyleOption(option)
        reference = panel.schedule.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, option,
            QStyle.SubControl.SC_ComboBoxEditField, panel.schedule)
        for field in (panel.keep_count, panel.keep_days, panel.interval_hours, panel.time, panel.month_day):
            if field.isVisible():
                editor = field.lineEdit()
                self.assertEqual(editor.x() + editor.textMargins().left(), reference.left())
        if width == 900:
            self.assertEqual(panel.keep_count.mapTo(panel, QPoint()).y(), panel.keep_days.mapTo(panel, QPoint()).y())
            if panel.time.isVisible():
                self.assertEqual(panel.schedule.mapTo(panel, QPoint()).y(), panel.time.mapTo(panel, QPoint()).y())

    @staticmethod
    def capture(widget, name):
        destination = os.environ.get("WORKLOGGER_SCREENSHOTS")
        if destination:
            path = Path(destination)
            path.mkdir(parents=True, exist_ok=True)
            widget.grab().save(str(path / (name + ".png")))
