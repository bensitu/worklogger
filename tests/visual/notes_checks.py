"""Opt-in layout checks for the note workspace across languages and themes."""

from datetime import date
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, qInstallMessageHandler
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from worklogger.app.use_cases.ai import RewriteTextHandler
from worklogger.app.use_cases.notes import DailyNotesService
from worklogger.domain.notes.models import DailyNote
from worklogger.infrastructure.database import MigrationRunner, SQLiteConnectionFactory
from worklogger.infrastructure.export import MarkdownExporter
from worklogger.infrastructure.i18n import available_languages, get_language, set_language
from worklogger.infrastructure.repositories import SQLiteAuthRepository, SQLiteDailyNoteRepository, SQLiteQuickLogRepository, SQLiteSettingsRepository
from worklogger.infrastructure.security import PBKDF2PasswordHasher
from worklogger.presentation.job_runner import ImmediateJobRunner
from worklogger.presentation.notes import NoteEditorDialog
from worklogger.presentation.theme import configure_application_style, install_bundled_fonts
from worklogger.presentation.theme.theme_engine import ThemeEngine
from worklogger.presentation.viewmodels.notes import NoteEditorViewModel
from worklogger.presentation.widgets.feedback import information_dialog
from worklogger.infrastructure.i18n import _


class NotesLayoutChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        configure_application_style()
        install_bundled_fonts()

    def test_workspace_fits_supported_sizes_languages_and_themes(self):
        language, stylesheet, palette = get_language(), self.app.styleSheet(), self.app.palette()
        warnings = []
        previous = qInstallMessageHandler(lambda kind, context, message: warnings.append(message))
        try:
            with tempfile.TemporaryDirectory() as directory:
                factory = SQLiteConnectionFactory(Path(directory) / "notes.db")
                MigrationRunner(factory).run_pending()
                user = SQLiteAuthRepository(factory, password_hasher=PBKDF2PasswordHasher(iterations=1000)).create_user(
                    "sample.user", "example-password", recovery_key=None, is_admin=False)
                notes = SQLiteDailyNoteRepository(factory)
                for day in (8, 7, 5, 2):
                    notes.save(DailyNote(user.id, date(2026, 10, day), "Meeting notes and follow-up tasks " * 12))
                service = DailyNotesService(user_id=user.id, notes=notes, settings=SQLiteSettingsRepository(factory),
                                           previous_entries=SQLiteQuickLogRepository(factory))
                model = NoteEditorViewModel(service, markdown_exporter=MarkdownExporter(), rewrite_handler=RewriteTextHandler())
                engine = ThemeEngine()
                for language_code in available_languages():
                    set_language(language_code)
                    for dark in (False, True):
                        self.app.setPalette(engine.qt_palette(dark=dark))
                        self.app.setStyleSheet(engine.application_stylesheet(dark=dark))
                        dialog = NoteEditorDialog(model, date(2026, 10, 9), job_runner=ImmediateJobRunner())
                        try:
                            self.assertTrue(dialog.refresh())
                            dialog.show()
                            for width, height in ((760, 520), (1000, 720)):
                                dialog.resize(width, height)
                                self.app.processEvents()
                                self.assertEqual((dialog.width(), dialog.height()), (width, height))
                                self.assertEqual(dialog.history_list.horizontalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                                for row in range(dialog.history_list.count()):
                                    self.assertGreaterEqual(dialog.history_list.visualItemRect(dialog.history_list.item(row)).height(), 64)
                                self.assertLess(dialog.date_label.mapTo(dialog, dialog.date_label.rect().bottomLeft()).y(),
                                                dialog.editor.mapTo(dialog, dialog.editor.rect().topLeft()).y())
                                controls = (dialog.search_input, dialog.editor, dialog.date_label, dialog.rewrite_button,
                                            dialog.copy_button, dialog.export_button, dialog.reload_button, dialog.save_button,
                                            dialog.close_button, dialog.report_checkbox, dialog.ai_checkbox)
                                for widget in controls:
                                    rect = widget.rect().translated(widget.mapTo(dialog, widget.rect().topLeft()))
                                    self.assertTrue(dialog.rect().contains(rect), (language_code, dark, widget.objectName()))
                                self.capture(dialog, f"{language_code}-notes-{'dark' if dark else 'light'}-{width}-empty")
                            dialog.activateWindow()
                            dialog.search_input.setFocus()
                            self.app.processEvents()
                            QTest.keyClicks(dialog.search_input, "Meeting")
                            dialog._search_timer.stop()
                            dialog._search()
                            self.app.processEvents()
                            self.assertTrue(dialog.search_input.hasFocus())
                            QTest.keyClicks(dialog.search_input, " notes")
                            self.assertEqual(dialog.search_input.text(), "Meeting notes")
                            dialog.search_input.clear()
                            dialog._search_timer.stop()
                            dialog._search()
                            dialog._select_note(dialog.history_list.item(1))
                            self.app.processEvents()
                            self.assertTrue(dialog.copy_button.isEnabled())
                            self.capture(dialog, f"{language_code}-notes-{'dark' if dark else 'light'}-content")
                            feedback = information_dialog(dialog, _("Notes"), _("Note saved."),
                                detail=_("Your changes have been saved for {date}.").format(date="2026-10-08"))
                            try:
                                feedback.show()
                                self.app.processEvents()
                                self.assertGreaterEqual(feedback.width(), 360)
                                self.capture(feedback, f"{language_code}-note-saved-{'dark' if dark else 'light'}")
                            finally:
                                feedback.hide()
                                feedback.deleteLater()
                        finally:
                            dialog._draft_timer.stop()
                            dialog._search_timer.stop()
                            dialog.hide()
                            dialog.deleteLater()
                self.assertFalse(any("Point size <= 0" in warning for warning in warnings), warnings)
        finally:
            qInstallMessageHandler(previous)
            set_language(language)
            self.app.setPalette(palette)
            self.app.setStyleSheet(stylesheet)

    def capture(self, widget, name):
        directory = os.environ.get("WORKLOGGER_SCREENSHOTS")
        if directory:
            path = Path(directory)
            path.mkdir(parents=True, exist_ok=True)
            self.assertTrue(widget.grab().save(str(path / f"{name}.png")))
