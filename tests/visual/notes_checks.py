"""Opt-in layout checks for the note workspace across languages and themes."""

from datetime import date, timedelta
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, Qt, qInstallMessageHandler
from PySide6.QtGui import QEnterEvent, QHoverEvent
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
from tests.job_runner import ImmediateJobRunner
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
                for offset in range(62):
                    notes.save(DailyNote(user.id, date(2026, 1, 1) + timedelta(days=offset), "Saved meeting notes"))
                service = DailyNotesService(user_id=user.id, notes=notes, settings=SQLiteSettingsRepository(factory),
                                           previous_entries=SQLiteQuickLogRepository(factory))
                model = NoteEditorViewModel(service, markdown_exporter=MarkdownExporter(), rewrite_handler=RewriteTextHandler())
                engine = ThemeEngine()
                for language_code in available_languages():
                    set_language(language_code)
                    variants = (("blue", False), ("blue", True))
                    if language_code == "en_US":
                        variants += (("liquid_glass", False), ("liquid_glass", True))
                    for theme, dark in variants:
                        engine.apply_to(self.app, theme, dark=dark)
                        capture_prefix = f"{language_code}-{theme}"
                        dialog = NoteEditorDialog(model, date(2026, 10, 9), job_runner=ImmediateJobRunner())
                        try:
                            self.assertTrue(dialog.refresh())
                            dialog.show()
                            for width, height in ((760, 520), (1000, 720)):
                                dialog.resize(width, height)
                                self.app.processEvents()
                                self.assertEqual((dialog.width(), dialog.height()), (width, height))
                                self.assert_period_controls_aligned(dialog.history_browser)
                                self.assertEqual(dialog.history_list.horizontalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                                for row in range(dialog.history_list.count()):
                                    self.assertGreaterEqual(dialog.history_list.visualItemRect(dialog.history_list.item(row)).height(), 64)
                                self.assertLess(dialog.date_label.mapTo(dialog, dialog.date_label.rect().bottomLeft()).y(),
                                                dialog.editor.mapTo(dialog, dialog.editor.rect().topLeft()).y())
                                controls = (dialog.search_input, dialog.editor, dialog.date_label, dialog.rewrite_button,
                                            dialog.copy_button, dialog.export_button, dialog.reload_button, dialog.save_button,
                                            dialog.close_button, dialog.delete_button, dialog.report_checkbox, dialog.ai_checkbox)
                                for widget in controls:
                                    rect = widget.rect().translated(widget.mapTo(dialog, widget.rect().topLeft()))
                                    self.assertTrue(dialog.rect().contains(rect), (language_code, dark, widget.objectName()))
                                tools = (dialog.export_button, dialog.copy_button, dialog.reload_button)
                                self.assertEqual({(tool.width(), tool.height()) for tool in tools}, {(40, 40)})
                                self.assertLess(dialog.export_button.x(), dialog.copy_button.x())
                                self.assertLess(dialog.copy_button.x(), dialog.reload_button.x())
                                self.assertIs(dialog.export_button.nextInFocusChain(), dialog.copy_button)
                                self.assertIs(dialog.copy_button.nextInFocusChain(), dialog.reload_button)
                                for tool in (dialog.copy_button, dialog.reload_button):
                                    enabled = tool.isEnabled()
                                    for state in (True, False):
                                        tool.setEnabled(state)
                                        self.app.processEvents()
                                        rendered = tool.grab().toImage()
                                        self.assertNotEqual(rendered.pixelColor(0, tool.height() // 2),
                                                            rendered.pixelColor(4, tool.height() // 2))
                                        self.assertEqual((tool.width(), tool.height()), (40, 40))
                                    tool.setEnabled(enabled)
                                self.capture(dialog, f"{capture_prefix}-notes-{'dark' if dark else 'light'}-{width}-empty")
                            dialog.activateWindow()
                            self.app.processEvents()
                            viewport = dialog.history_list.viewport()
                            first_rect = dialog.history_list.visualItemRect(dialog.history_list.item(0))
                            sample = QPoint(first_rect.left() + 3, first_rect.center().y())
                            self.app.sendEvent(viewport, QEvent(QEvent.Type.Leave))
                            self.app.processEvents()
                            before = viewport.grab().toImage().scaled(viewport.size()).pixelColor(sample)
                            self.hover_item(dialog.history_list, 0)
                            self.app.processEvents()
                            after = viewport.grab().toImage().scaled(viewport.size()).pixelColor(sample)
                            self.assertNotEqual(before, after, (language_code, theme, dark))
                            self.assertIsNone(dialog.history_list.currentItem())
                            self.assertEqual(dialog.editor.toPlainText(), "")
                            self.capture(dialog, f"{capture_prefix}-notes-{'dark' if dark else 'light'}-hover")
                            self.app.sendEvent(viewport, QEvent(QEvent.Type.Leave))
                            dialog.activateWindow()
                            dialog.search_input.setFocus()
                            self.app.processEvents()
                            QTest.keyClicks(dialog.search_input, "Meeting")
                            dialog.history_browser.refresh()
                            self.app.processEvents()
                            self.assertTrue(dialog.search_input.hasFocus())
                            QTest.keyClicks(dialog.search_input, " notes")
                            self.assertEqual(dialog.search_input.text(), "Meeting notes")
                            dialog.search_input.setText("no matching note")
                            dialog.history_browser.refresh()
                            self.app.processEvents()
                            self.assertTrue(dialog.empty_label.isVisible())
                            self.assertLess(dialog.empty_label.geometry().bottom(), dialog.history_list.y())
                            self.capture(dialog, f"{capture_prefix}-notes-{'dark' if dark else 'light'}-no-results")
                            dialog.search_input.clear()
                            dialog.history_browser.refresh()
                            dialog._select_note(dialog.history_list.item(1))
                            self.app.processEvents()
                            self.assertTrue(dialog.copy_button.isEnabled())
                            selected_row = dialog.history_list.currentRow()
                            selected_rect = dialog.history_list.visualItemRect(dialog.history_list.currentItem())
                            sample = QPoint(selected_rect.left() + 3, selected_rect.center().y())
                            before = viewport.grab().toImage().scaled(viewport.size()).pixelColor(sample)
                            self.hover_item(dialog.history_list, selected_row)
                            self.app.processEvents()
                            after = viewport.grab().toImage().scaled(viewport.size()).pixelColor(sample)
                            self.assertEqual(before, after)
                            self.app.sendEvent(viewport, QEvent(QEvent.Type.Leave))
                            self.capture(dialog, f"{capture_prefix}-notes-{'dark' if dark else 'light'}-content")
                            browser = dialog.history_browser
                            for mode in ("year", "custom", "all"):
                                browser.mode_input.setCurrentIndex(browser.mode_input.findData(mode))
                                browser.start_input.setDate(date(2026, 1, 1))
                                browser.end_input.setDate(date(2026, 12, 31))
                                browser.refresh()
                                self.assertEqual(browser.history_list.count(), 50)
                                for width, height in ((760, 520), (1000, 720)):
                                    dialog.resize(width, height)
                                    self.app.processEvents()
                                    self.assertEqual((dialog.width(), dialog.height()), (width, height))
                                    self.assertGreaterEqual(browser.history_list.height(), 64)
                                    if mode == "year":
                                        self.assert_period_controls_aligned(browser)
                                    if mode == "custom":
                                        self.assertEqual(browser.start_input.x(), browser.end_input.x())
                                        self.assertEqual(browser.start_input.size(), browser.end_input.size())
                                    controls = [browser.mode_input, browser.search_input,
                                                browser.range_label, browser.count_label, browser.history_list,
                                                browser.more_button]
                                    controls += ([browser.start_input, browser.end_input] if mode == "custom" else
                                                 [browser.period_button] if mode == "year" else [])
                                    rectangles = []
                                    for widget in controls:
                                        rect = widget.rect().translated(widget.mapTo(dialog, widget.rect().topLeft()))
                                        self.assertTrue(dialog.rect().contains(rect), (language_code, mode, widget))
                                        self.assertTrue(all(not rect.intersects(other) for other in rectangles),
                                                        (language_code, mode, widget))
                                        rectangles.append(rect)
                                    self.capture(dialog, f"{capture_prefix}-notes-{'dark' if dark else 'light'}-{width}-{mode}")
                                    if mode == "all":
                                        count_text = browser.count_label.text()
                                        browser._set_loading(True)
                                        self.app.processEvents()
                                        self.assertTrue(browser.loading_bar.isVisible())
                                        self.assertTrue(browser.mode_input.isEnabled())
                                        self.assertTrue(browser.search_input.isEnabled())
                                        self.assertTrue(dialog.editor.isEnabled())
                                        self.assertFalse(browser.more_button.isEnabled())
                                        self.assertLess(browser.count_label.geometry().right(), browser.loading_bar.x())
                                        self.capture(dialog, f"{capture_prefix}-notes-{'dark' if dark else 'light'}-{width}-loading")
                                        browser._set_loading(False)
                                        browser.count_label.setText(count_text)
                                scrollbar = browser.history_list.verticalScrollBar()
                                scrollbar.setValue(scrollbar.maximum())
                                scroll_position = scrollbar.value()
                                browser.more_button.click()
                                self.app.processEvents()
                                self.assertEqual(browser.history_list.count(), 66)
                                self.assertTrue(browser.more_button.isHidden())
                                self.assertEqual(scrollbar.value(), scroll_position)
                            browser.mode_input.setCurrentIndex(browser.mode_input.findData("custom"))
                            browser.start_input.setDate(date(2027, 1, 1))
                            browser.refresh()
                            self.app.processEvents()
                            self.assertEqual(browser.history_list.count(), 0)
                            self.assertTrue(browser.more_button.isHidden())
                            self.capture(dialog, f"{capture_prefix}-notes-{'dark' if dark else 'light'}-invalid-range")
                            feedback = information_dialog(dialog, _("Notes"), _("Note saved."),
                                detail=_("Your changes have been saved for {date}.").format(date="2026-10-08"))
                            try:
                                feedback.show()
                                self.app.processEvents()
                                self.assertGreaterEqual(feedback.width(), 360)
                                self.capture(feedback, f"{capture_prefix}-note-saved-{'dark' if dark else 'light'}")
                            finally:
                                feedback.hide()
                                feedback.deleteLater()
                        finally:
                            dialog._draft_timer.stop()
                            dialog.history_browser.stop()
                            dialog.hide()
                            dialog.deleteLater()
                self.assertFalse(any("Point size <= 0" in warning for warning in warnings), warnings)
        finally:
            qInstallMessageHandler(previous)
            set_language(language)
            self.app.setPalette(palette)
            self.app.setStyleSheet(stylesheet)

    def assert_period_controls_aligned(self, browser):
        bounds = {(button.y(), button.height()) for button in
                  (browser.previous_button, browser.period_button, browser.next_button)}
        self.assertEqual(len(bounds), 1, bounds)

    def hover_item(self, widget, row):
        viewport = widget.viewport()
        point = widget.visualItemRect(widget.item(row)).center()
        global_point = viewport.mapToGlobal(point)
        self.app.sendEvent(viewport, QEnterEvent(point, viewport.mapTo(viewport.window(), point), global_point))
        self.app.sendEvent(viewport, QHoverEvent(QEvent.Type.HoverMove, point, global_point, QPoint(-1, -1)))

    def capture(self, widget, name):
        directory = os.environ.get("WORKLOGGER_SCREENSHOTS")
        if directory:
            path = Path(directory)
            path.mkdir(parents=True, exist_ok=True)
            self.assertTrue(widget.grab().save(str(path / f"{name}.png")))
