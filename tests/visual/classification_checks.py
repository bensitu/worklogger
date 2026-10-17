"""Opt-in classification layout checks for the calendar rail and minimal view."""

from datetime import date
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QPoint
from PySide6.QtWidgets import QApplication

from worklogger.domain.projects.models import Project, WorkContext, WorkItem
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import EntryType, WorkLog, WorkMode
from worklogger.infrastructure.i18n import available_languages, get_language, set_language
from worklogger.presentation.job_runner import ImmediateJobRunner
from worklogger.presentation.shell.minimal_view import MinimalView, MinimalViewConfig
from worklogger.presentation.theme import ThemeEngine, configure_application_style, install_bundled_fonts
from tests.presentation.test_app_window import MemoryWorkLogRepository, _entry_model, _window


class ClassificationLayoutChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        configure_application_style()
        install_bundled_fonts()

    def test_classification_fits_rail_and_minimal_view_in_representative_locales(self):
        old_language = get_language()
        old_palette, old_style = self.app.palette(), self.app.styleSheet()
        old_context = self.app.property("worklogger_theme_context")
        project = Project(uuid4().hex, "Payment Platform / International Services")
        item = WorkItem(uuid4().hex, project.id, "API Authentication and Authorization Review")
        context = WorkContext(project.id, item.id, project.name, item.title)
        projects = SimpleNamespace(catalog=lambda: Result.success(((project,), {project.id: (item,)})),
                                   recent_contexts=lambda: Result.success((context,)))
        try:
            for language in available_languages():
                set_language(language)
                for dark in (False, True):
                    for minimal in (False, True):
                        repository = MemoryWorkLogRepository()
                        record = repository.save_entry(WorkLog(1, date(2026, 4, 20), "09:00", "10:00",
                            entry_type=EntryType.MEETING, work_mode=WorkMode.REMOTE, context=context))
                        if minimal:
                            model = _entry_model(repository)
                            model.service.projects = projects
                            window = MinimalView(time_entry_view_model=model,
                                job_runner=ImmediateJobRunner(), config=MinimalViewConfig(
                                    selected_day=record.day, today=record.day, theme="green", dark=dark))
                            window.resize(680, 760)
                        else:
                            window = _window(repository)
                            window.entry_panel.view_model.service.projects = projects
                            window.entry_panel.refresh_projects()
                            window.resize(1100, 800)
                        try:
                            ThemeEngine().apply_to(self.app, "green", dark=dark)
                            window.refresh()
                            window.show()
                            self.app.processEvents()
                            panel = window.entry_panel
                            panel.edit_entry(record)
                            self.app.processEvents()
                            self.assertIn(context.label, panel.classification_button.accessibleDescription())
                            self.assertTrue(panel.rect().contains(panel.classification_button.geometry()))
                            prefix = f"{language}-{'dark' if dark else 'light'}-{'minimal' if minimal else 'calendar'}"
                            self.capture(window, prefix + "-collapsed")
                            for automatic in (False, True):
                                panel.time_tabs.setCurrentIndex(int(automatic))
                                self.app.processEvents()
                                panel.classification_button.click()
                                self.app.processEvents()
                                popup = panel._classification_popup
                                self.assertTrue(popup.isVisible())
                                self.assertTrue(popup.isWindow())
                                self.assertTrue(popup.screen().availableGeometry().contains(popup.frameGeometry()))
                                for field in (popup.period_type_combo, popup.work_mode_combo,
                                              popup.context_picker.project_combo, popup.context_picker.work_item_combo,
                                              popup.apply_button, popup.cancel_button):
                                    bounds = field.rect().translated(field.mapTo(popup, QPoint()))
                                    self.assertTrue(popup.rect().contains(bounds), (prefix, field.objectName()))
                                self.assertTrue(popup.section_tabs.isTabEnabled(0))
                                self.assertEqual(popup.section_tabs.isTabEnabled(1), not automatic)
                                self.capture(popup, prefix + ("-auto" if automatic else "-work"))
                                if not automatic:
                                    popup.section_tabs.setCurrentIndex(1)
                                    self.app.processEvents()
                                    self.assertTrue(popup.leave_type_combo.isVisible())
                                    self.assertFalse(popup.work_mode_combo.isVisible())
                                    self.capture(popup, prefix + "-leave")
                                popup.cancel_button.click()
                        finally:
                            window.hide()
                            window.deleteLater()
                            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        finally:
            set_language(old_language)
            self.app.setPalette(old_palette)
            self.app.setStyleSheet(old_style)
            self.app.setProperty("worklogger_theme_context", old_context)

    @staticmethod
    def capture(widget, name):
        destination = os.environ.get("WORKLOGGER_SCREENSHOTS")
        if destination:
            path = Path(destination)
            path.mkdir(parents=True, exist_ok=True)
            widget.grab().save(str(path / (name + ".png")))
