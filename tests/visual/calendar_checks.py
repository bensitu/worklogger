from contextlib import contextmanager
from dataclasses import replace
from datetime import date
from itertools import product
import os
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QFrame, QVBoxLayout, QWidget

from worklogger.domain.calendar.models import CalendarEvent
from worklogger.domain.worklog.models import WorkLog, EntryType, CustomEntryType
from worklogger.infrastructure.i18n import available_languages, set_language
from worklogger.infrastructure.repositories import SQLiteCalendarEventRepository, SQLiteWorkLogRepository
from tests.presentation.test_app_window import MemoryWorkLogRepository, _window


class ReadOnlyDatabase:
    def __init__(self, path):
        self.path = Path(path).resolve()

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()


def may_records():
    records = MemoryWorkLogRepository()
    events = tuple(CalendarEvent(
        index, 1, date(2026, 5, 21), f"Meeting {index}", "13:00", "14:00",
    ) for index in range(1, 7))
    for day in range(1, 32):
        if date(2026, 5, day).weekday() < 5:
            records.save(WorkLog(1, date(2026, 5, day), "09:00", "18:30", 1.0,
                                 "Feature work", EntryType.NORMAL))
    records.save(WorkLog(1, date(2026, 5, 21), "22:00", "07:30", 1.0,
                         "Night shift", EntryType.BUSINESS_TRIP))
    selected = date(2026, 5, 21)
    database = os.environ.get("WORKLOGGER_QA_DATABASE")
    if database:
        factory = ReadOnlyDatabase(database)
        with factory.connection() as connection:
            row = connection.execute(
                "SELECT user_id FROM worklog WHERE d BETWEEN ? AND ? GROUP BY user_id ORDER BY COUNT(*) DESC",
                ("2026-05-01", "2026-05-31"),
            ).fetchone()
        if row is None:
            raise AssertionError("The QA database contains no May 2026 work logs")
        user_id = row["user_id"]
        imported = SQLiteWorkLogRepository(factory).list_for_month(user_id, 2026, 5)
        records.records.clear()
        for record in imported:
            records.save(replace(record, user_id=1))
        events = tuple(replace(event, user_id=1) for event in
                       SQLiteCalendarEventRepository(factory).list_for_range(user_id, date(2026, 5, 1), date(2026, 5, 31)))
        if records.get_for_day(1, selected) is None:
            selected = imported[-1].day
    return records, events, selected


class CalendarLayoutChecks(unittest.TestCase):
    def test_entry_type_popup_previews_match_calendar_colors_across_languages_and_themes(self):
        from PySide6.QtWidgets import QComboBox, QStyle, QStyleOptionComboBox, QStyleOptionViewItem
        from worklogger.presentation.theme import ThemeEngine, configure_application_style, install_bundled_fonts
        from worklogger.presentation.widgets.entry_type_options import add_entry_type_option

        configure_application_style()
        install_bundled_fonts()
        engine = ThemeEngine()
        old_style, old_palette = self.app.styleSheet(), self.app.palette()
        old_context = self.app.property("worklogger_theme_context")
        try:
            for language, theme, dark in product(available_languages(), ("blue", "liquid_glass"), (False, True)):
                set_language(language)
                engine.apply_to(self.app, theme, dark=dark)
                panel = QWidget()
                panel.setObjectName("worklog_entry_panel_widget")
                panel.setProperty("compact", True)
                panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
                layout = QVBoxLayout(panel)
                combo = QComboBox(panel)
                layout.addWidget(combo)
                try:
                    for definition in EntryType:
                        add_entry_type_option(combo, definition)
                    combo.setFixedWidth(88)
                    panel.show()
                    for value in ("normal", "remote"):
                        combo.setCurrentIndex(combo.findData(value))
                        self.app.processEvents()
                        option = QStyleOptionComboBox()
                        combo.initStyleOption(option)
                        text_rect = combo.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, option,
                            QStyle.SubControl.SC_ComboBoxEditField, combo)
                        reserved = 0 if option.currentIcon.isNull() else option.iconSize.width() + 4
                        if language == "en_US":
                            self.assertLessEqual(combo.fontMetrics().horizontalAdvance(combo.currentText()),
                                                 text_rect.width() - reserved, (theme, dark, value))
                        directory = os.environ.get("WORKLOGGER_SCREENSHOTS")
                        if directory:
                            target = Path(directory)
                            target.mkdir(parents=True, exist_ok=True)
                            self.assertTrue(combo.grab().save(str(target /
                                f"work-type-closed-{language}-{theme}-{dark}-{value}.png")))
                    combo.setCurrentIndex(combo.findData("remote"))
                    combo.setFixedWidth(max(220, combo.sizeHint().width()))
                    combo.showPopup()
                    self.app.processEvents()
                    text_offsets = set()
                    for row in range(combo.count()):
                        index = combo.model().index(row, combo.modelColumn(), combo.rootModelIndex())
                        item_option = QStyleOptionViewItem()
                        item_option.initFrom(combo.view())
                        combo.itemDelegate().initStyleOption(item_option, index)
                        item_option.rect = combo.view().visualRect(index)
                        text_rect = combo.view().style().subElementRect(
                            QStyle.SubElement.SE_ItemViewItemText, item_option, combo.view())
                        text_offsets.add(text_rect.left() - item_option.rect.left())
                    self.assertEqual(len(text_offsets), 1, (language, theme, dark, text_offsets))
                    popup = combo.view().window()
                    image = popup.grab().toImage()
                    colors = {image.pixelColor(x, y).name()
                              for x in range(image.width()) for y in range(image.height())}
                    for definition in EntryType:
                        color = engine.entry_type_color(definition, dark=dark)
                        self.assertIn(color, colors)
                    directory = os.environ.get("WORKLOGGER_SCREENSHOTS")
                    if directory:
                        target = Path(directory)
                        target.mkdir(parents=True, exist_ok=True)
                        self.assertTrue(popup.grab().save(str(target / f"work-types-{language}-{theme}-{dark}.png")))
                finally:
                    combo.hidePopup()
                    panel.close()
                    panel.deleteLater()
        finally:
            self.app.setStyleSheet(old_style)
            self.app.setPalette(old_palette)
            self.app.setProperty("worklogger_theme_context", old_context)

    def test_classification_segments_render_at_the_bottom_in_light_dark_and_selected_cells(self):
        from tests.presentation.test_qt_widgets import _calendar_state
        from worklogger.presentation.theme import ThemeEngine
        from worklogger.presentation.viewmodels.calendar import CalendarIndicatorSegment
        from worklogger.presentation.widgets.calendar import CalendarDayButton

        engine = ThemeEngine()
        base = next(cell for cell in _calendar_state().cells if cell.is_selected)
        old_style, old_palette = self.app.styleSheet(), self.app.palette()
        old_context = self.app.property("worklogger_theme_context")
        button = CalendarDayButton()
        button.setFixedSize(84, 110)
        types = (*EntryType, CustomEntryType("custom:00000000000000000000000000000001", "Research"))
        try:
            for theme, dark, selected in product(("blue", "liquid_glass"), (False, True), (False, True)):
                engine.apply_to(self.app, theme, dark=dark)
                style = engine.calendar_cell_style({"selected"} if selected else set(), theme=theme, dark=dark)
                for entry_type in types:
                    color = engine.entry_type_color(entry_type, dark=dark)
                    cell = replace(base, segments=(CalendarIndicatorSegment(entry_type.value, 1.0, color),),
                                   is_selected=selected, style=style)
                    button.set_cell(replace(cell, segments=()))
                    before = button.grab().toImage().scaled(button.size())
                    button.set_cell(cell)
                    after = button.grab().toImage().scaled(button.size())
                    indicator_y, row = self._classification_row(after, {color})
                    self.assertGreater(indicator_y, after.height() * 3 / 4)
                    self.assertIn(color, row)
                    changed = [(x, y) for y in range(after.height()) for x in range(after.width())
                               if after.pixel(x, y) != before.pixel(x, y)]
                    self.assertTrue(changed)
                    self.assertTrue(all(0 < x < button.width() - 1
                                        and y > button.height() * 3 / 4
                                        for x, y in changed))
                    directory = os.environ.get("WORKLOGGER_SCREENSHOTS")
                    if directory:
                        target = Path(directory)
                        target.mkdir(parents=True, exist_ok=True)
                        self.assertTrue(button.grab().save(str(target /
                            f"classification-{theme}-{dark}-{selected}-{entry_type.value.replace(':', '-')}.png")))
                segments = tuple(CalendarIndicatorSegment(definition.value, duration,
                    engine.entry_type_color(definition, dark=dark)) for definition, duration in
                    ((EntryType.NORMAL, 3.0), (EntryType.MEETING, 1.0), (EntryType.PAID_LEAVE, 2.0)))
                for width in (48, 84):
                    button.setFixedSize(width, 110)
                    button.set_cell(replace(base, segments=segments, is_selected=selected, style=style))
                    image = button.grab().toImage().scaled(button.size())
                    indicator_y, row = self._classification_row(image, {segment.color for segment in segments})
                    self.assertGreater(indicator_y, image.height() * 3 / 4)
                    colored_width = sum(row.count(segment.color) for segment in segments)
                    self.assertGreater(colored_width, 0)
                    for segment in segments:
                        self.assertAlmostEqual(row.count(segment.color) / colored_width,
                            segment.duration / sum(item.duration for item in segments),
                            delta=1 / colored_width + 0.03)
                    directory = os.environ.get("WORKLOGGER_SCREENSHOTS")
                    if directory:
                        target = Path(directory)
                        target.mkdir(parents=True, exist_ok=True)
                        self.assertTrue(button.grab().save(str(target /
                            f"classification-mixed-{theme}-{dark}-{selected}-{width}.png")))
                button.setFixedSize(84, 110)
        finally:
            button.deleteLater()
            self.app.setStyleSheet(old_style)
            self.app.setPalette(old_palette)
            self.app.setProperty("worklogger_theme_context", old_context)

    @staticmethod
    def _classification_row(image, colors):
        rows = ((y, [image.pixelColor(x, y).name() for x in range(image.width())])
                for y in range(image.height() // 2, image.height()))
        return max(rows, key=lambda item: sum(color in colors for color in item[1]))

    def test_note_markers_align_with_overnight_icons_and_preserve_event_badges(self):
        from tests.presentation.test_qt_widgets import _calendar_state
        from worklogger.presentation.theme import ThemeEngine, configure_application_style, install_bundled_fonts
        from worklogger.presentation.widgets.calendar import CalendarDayButton

        configure_application_style()
        install_bundled_fonts()
        engine = ThemeEngine()
        old_style, old_palette = self.app.styleSheet(), self.app.palette()
        old_context = self.app.property("worklogger_theme_context")
        base = next(cell for cell in _calendar_state().cells if cell.is_selected)
        button = CalendarDayButton()
        try:
            for theme in ("blue", "liquid_glass"):
                for dark in (False, True):
                    engine.apply_to(self.app, theme, dark=dark)
                    for selected, width in product((False, True), (48, 84)):
                        button.setFixedSize(width, 110)
                        for overnight in (False, True):
                            with self.subTest(theme=theme, dark=dark, selected=selected, overnight=overnight, width=width):
                                cell = replace(base, is_selected=selected, has_note_marker=False,
                                    show_overnight_marker=overnight, event_count=2,
                                    text_lines=("20", "8.0h", "+0.0h"),
                                    style=engine.calendar_cell_style({"selected"} if selected else set(),
                                                                    theme=theme, dark=dark))
                                button.set_cell(cell)
                                before = button.grab().toImage().scaled(button.size())
                                button.set_cell(replace(cell, has_note_marker=True))
                                after = button.grab().toImage().scaled(button.size())
                                changed = [(x, y) for y in range(after.height()) for x in range(after.width())
                                           if after.pixel(x, y) != before.pixel(x, y)]
                                self.assertTrue(changed)
                                left, right = min(x for x, _y in changed), max(x for x, _y in changed)
                                top, bottom = min(y for _x, y in changed), max(y for _x, y in changed)
                                self.assertLess(right, button.width() - (22 if overnight else 26))
                                self.assertLessEqual(abs((top + bottom) / 2 - (32 if width == 48 else 15)), 1)
                                self.assertLessEqual(right - left, 5)
                                self.assertLessEqual(bottom - top, 5)
                                target = os.environ.get("WORKLOGGER_SCREENSHOTS")
                                if target:
                                    Path(target).mkdir(parents=True, exist_ok=True)
                                    self.assertTrue(after.save(str(Path(target) /
                                        f"note-marker-{theme}-{dark}-{selected}-{overnight}-{width}.png")))
        finally:
            button.deleteLater()
            self.app.setStyleSheet(old_style)
            self.app.setPalette(old_palette)
            self.app.setProperty("worklogger_theme_context", old_context)

    def test_batch_context_and_recent_controls_fit_localized_layouts(self):
        from worklogger.presentation.widgets.batch_context import BatchContextDialog
        from worklogger.domain.projects.models import Project, WorkItem, WorkContext
        from worklogger.presentation.theme import ThemeEngine, configure_application_style, install_bundled_fonts
        from uuid import uuid4
        configure_application_style()
        install_bundled_fonts()
        project = Project(uuid4().hex, "Research")
        item = WorkItem(uuid4().hex, project.id, "Review")
        context = WorkContext(project.id, item.id, project.name, item.title)
        entries = (WorkLog(1, date(2026, 10, 10), "09:00", "10:00", id=1, context=context),
                   WorkLog(1, date(2026, 10, 10), "10:00", "11:00", id=2))
        old_style, old_palette = self.app.styleSheet(), self.app.palette()
        try:
            for language in available_languages():
                set_language(language)
                for dark in (False, True):
                    engine = ThemeEngine()
                    self.app.setPalette(engine.qt_palette(dark=dark))
                    self.app.setStyleSheet(engine.application_stylesheet(dark=dark))
                    dialog = BatchContextDialog(None, entries, (project,), {project.id: (item,)})
                    dialog.picker.set_recent((context,))
                    dialog.picker.recent_menu.actions()[0].trigger()
                    dialog.show()
                    self.app.processEvents()
                    self.assertEqual(dialog.picker.context(), context)
                    for field in (dialog.picker, dialog.records_list, dialog.apply_button):
                        self.assertTrue(dialog.rect().contains(field.mapTo(dialog, field.rect().bottomRight())))
                    directory = os.environ.get("WORKLOGGER_SCREENSHOTS")
                    if directory:
                        path = Path(directory)
                        path.mkdir(parents=True, exist_ok=True)
                        self.assertTrue(dialog.grab().save(str(path / f"{language}-batch-{dark}.png")))
                    dialog.close()
        finally:
            self.app.setStyleSheet(old_style)
            self.app.setPalette(old_palette)

    @classmethod
    def setUpClass(cls):
        from worklogger.presentation.theme import configure_application_style, install_bundled_fonts

        cls.app = QApplication.instance() or QApplication([])
        configure_application_style()
        install_bundled_fonts()

    def tearDown(self):
        set_language("en_US")

    def test_record_action_icons_and_undo_fit_keyboard_focus_and_localized_layouts(self):
        from tests.presentation.test_app_window import _entry_model
        from worklogger.domain.worklog.editing import EntryChangeInfo
        from worklogger.presentation.widgets.time_entries import TimeEntryPanel
        from worklogger.presentation.widgets.record_summary import RecordSummaryButton
        from worklogger.presentation.theme import ThemeEngine, configure_application_style, install_bundled_fonts
        configure_application_style()
        install_bundled_fonts()
        engine = ThemeEngine()
        old_style, old_palette = self.app.styleSheet(), self.app.palette()
        try:
            for language in available_languages():
                set_language(language)
                for dark in (False, True):
                    self.app.setPalette(engine.qt_palette(dark=dark))
                    self.app.setStyleSheet(engine.application_stylesheet(dark=dark))
                    repository = MemoryWorkLogRepository()
                    repository.changes_available = True
                    model = _entry_model(repository)
                    model.latest_change_info = EntryChangeInfo(1, "create", WorkLog(1, date(2026, 10, 10), "09:00", "12:00", id=1))
                    window = QWidget()
                    window.resize(330, 520)
                    root = QVBoxLayout(window)
                    panel = TimeEntryPanel(model)
                    row = RecordSummaryButton("09:00 - 12:00  3h 0m\nResearch / Review\nSource material", deletable=True, actions_enabled=True)
                    root.addWidget(panel)
                    root.addWidget(row)
                    root.addStretch()
                    try:
                        window.show()
                        row.actions_button.setFocus(Qt.FocusReason.TabFocusReason)
                        self.app.processEvents()
                        row.update_delete_visibility(row.mapToGlobal(QPoint(10, 10)))
                        self.assertTrue(panel.undo_button.isVisible())
                        self.assertEqual(panel.save_button.height(), panel.clear_button.height())
                        self.assertEqual(panel.save_button.height(), panel.undo_button.height())
                        for button in (row.actions_button, row.delete_button):
                            self.assertTrue(button.isVisible())
                            self.assertTrue(row.rect().contains(button.geometry()))
                            self.assertFalse(button.geometry().intersects(row.label.geometry()))
                            self.assertFalse(button.icon().pixmap(20, 20).isNull())
                        self.assertFalse(row.actions_button.geometry().intersects(row.delete_button.geometry()))
                        target = os.environ.get("WORKLOGGER_SCREENSHOTS")
                        if target:
                            Path(target).mkdir(parents=True, exist_ok=True)
                            self.assertTrue(window.grab().save(str(Path(target) / f"{language}-record-actions-{'dark' if dark else 'light'}.png")))
                    finally:
                        window.hide()
                        window.deleteLater()
        finally:
            self.app.setPalette(old_palette)
            self.app.setStyleSheet(old_style)

    def _project_context_service(self):
        import tempfile
        from worklogger.app.use_cases.projects import ProjectService
        from worklogger.infrastructure.database import SQLiteConnectionFactory, MigrationRunner
        from worklogger.infrastructure.repositories import SQLiteAuthRepository
        from worklogger.infrastructure.repositories.project_sqlite import SQLiteProjectRepository
        from worklogger.infrastructure.security import PBKDF2PasswordHasher
        directory = self.enterContext(tempfile.TemporaryDirectory())
        factory = SQLiteConnectionFactory(Path(directory) / "projects.db")
        MigrationRunner(factory).run_pending()
        user = SQLiteAuthRepository(factory, password_hasher=PBKDF2PasswordHasher(iterations=1000)).create_user(
            "sample", "synthetic-password", recovery_key=None, is_admin=False)
        service = ProjectService(user.id, SQLiteProjectRepository(factory))
        project = service.save_project("International research and development", "R1").value
        item = service.save_work_item(project.id, "Review the collected source material", "https://example.test/issue/1").value
        return service, project, item

    def test_project_management_fits_supported_languages_and_window_sizes(self):
        from worklogger.presentation.viewmodels.projects import ProjectManagerViewModel
        from worklogger.presentation.widgets.project_manager import ProjectManagerDialog
        from worklogger.presentation.job_runner import ImmediateJobRunner
        from worklogger.presentation.theme import ThemeEngine, configure_application_style, install_bundled_fonts
        configure_application_style()
        install_bundled_fonts()
        engine = ThemeEngine()
        service, _project, _item = self._project_context_service()
        old_style, old_palette = self.app.styleSheet(), self.app.palette()
        try:
            for language in available_languages():
                set_language(language)
                for dark in (False, True):
                    self.app.setPalette(engine.qt_palette(dark=dark))
                    self.app.setStyleSheet(engine.application_stylesheet(dark=dark))
                    dialog = ProjectManagerDialog(ProjectManagerViewModel(service), job_runner=ImmediateJobRunner())
                    try:
                        dialog.show()
                        for width, height in ((780, 580), (840, 640)):
                            dialog.resize(width, height)
                            for tab in (0, 1):
                                dialog.editor_tabs.setCurrentIndex(tab)
                                if tab:
                                    dialog.work_item_list.setCurrentRow(0)
                                self.app.processEvents()
                                self.assertEqual((dialog.width(), dialog.height()), (width, height))
                                fields = ((dialog.project_name_input, dialog.project_code_input,
                                           dialog.project_archive_button, dialog.project_save_button) if not tab else
                                          (dialog.work_item_list, dialog.work_item_title_input, dialog.work_item_url_input,
                                           dialog.work_item_save_button, dialog.work_item_new_button, dialog.work_item_archive_button))
                                for field in (dialog.project_list, dialog.project_new_button, dialog.close_button, *fields):
                                    self.assertTrue(dialog.rect().contains(field.rect().translated(field.mapTo(dialog, QPoint()))))
                                self.assertEqual(dialog.project_list.horizontalScrollBar().maximum(), 0)
                                self.assertFalse(dialog.project_new_button.geometry().intersects(dialog.project_list.geometry()))
                                target = os.environ.get("WORKLOGGER_SCREENSHOTS")
                                if target:
                                    Path(target).mkdir(parents=True, exist_ok=True)
                                    self.assertTrue(dialog.grab().save(str(Path(target) /
                                        f"{language}-projects-manager-{dark}-{width}-{tab}.png")))
                    finally:
                        dialog.close()
                        dialog.deleteLater()
        finally:
            self.app.setPalette(old_palette)
            self.app.setStyleSheet(old_style)

    def test_project_context_fits_supported_languages_and_window_sizes(self):
        from tests.presentation.test_app_window import _entry_model
        from worklogger.presentation.theme import ThemeEngine, configure_application_style, install_bundled_fonts
        configure_application_style()
        install_bundled_fonts()
        engine = ThemeEngine()
        old_style, old_palette = self.app.styleSheet(), self.app.palette()
        try:
            service, project, item = self._project_context_service()
            def model(repository):
                view_model = _entry_model(repository)
                view_model.service.projects = service
                return view_model
            for language in available_languages():
                set_language(language)
                for dark in (False, True):
                    self.app.setPalette(engine.qt_palette(dark=dark))
                    self.app.setStyleSheet(engine.application_stylesheet(dark=dark))
                    with patch("tests.presentation.test_app_window._entry_model", side_effect=model):
                        window = _window(MemoryWorkLogRepository())
                    try:
                        self.assertTrue(window.refresh())
                        window.entry_panel.classification_button.click()
                        popup = window.entry_panel._classification_popup
                        picker = popup.context_picker
                        picker.project_combo.setCurrentIndex(picker.project_combo.findData(project.id))
                        picker.work_item_combo.setCurrentIndex(picker.work_item_combo.findData(item.id))
                        popup.apply_button.click()
                        window.show()
                        for width, height in ((880, 580), (1100, 700)):
                            window.resize(width, height)
                            self.app.processEvents()
                            self.assertEqual((window.width(), window.height()), (width, height))
                            self.assertEqual(window.calendar_page.details_scroll.horizontalScrollBar().maximum(), 0)
                            self.assertGreaterEqual(window.calendar_page.records_scroll.height(), 96)
                            for field in (window.entry_panel.classification_button, window.entry_panel.save_button):
                                self.assertTrue(window.calendar_page.rect().contains(field.rect().translated(field.mapTo(window.calendar_page, QPoint()))))
                            viewport = window.calendar_page.details_scroll.viewport()
                            content = window.entry_panel.content_input
                            self.assertTrue(viewport.rect().contains(content.rect().translated(content.mapTo(viewport, QPoint()))))
                            target = os.environ.get("WORKLOGGER_SCREENSHOTS")
                            if target:
                                Path(target).mkdir(parents=True, exist_ok=True)
                                self.assertTrue(window.grab().save(str(Path(target) / f"{language}-projects-calendar-{'dark' if dark else 'light'}-{width}.png")))
                    finally:
                        window.close()
        finally:
            self.app.setPalette(old_palette)
            self.app.setStyleSheet(old_style)

    def test_record_search_controls_fit_localized_filters_and_results(self):
        from types import SimpleNamespace
        from worklogger.domain.projects.models import Project, WorkContext, WorkItem
        from worklogger.domain.worklog.search import EntryPage
        from worklogger.domain.shared.result import Result
        from worklogger.presentation.widgets.record_search import RecordSearchDialog
        from worklogger.presentation.job_runner import ImmediateJobRunner
        from worklogger.presentation.theme import ThemeEngine, configure_application_style, install_bundled_fonts
        configure_application_style()
        install_bundled_fonts()
        engine = ThemeEngine()
        old_style, old_palette = self.app.styleSheet(), self.app.palette()
        project = Project("1" * 32, "Research", archived=True)
        item = WorkItem("2" * 32, project.id, "Review", archived=True)
        record = WorkLog(1, date(2026, 10, 10), "09:00", "10:00", note="Source material", id=1,
                         context=WorkContext(project.id, item.id, project.name, item.title))
        model = SimpleNamespace(list_entry_types=lambda: Result.success(()),
            project_inventory=lambda: Result.success(((project,), {project.id: (item,)})),
            search=lambda _criteria, **_options: Result.success(EntryPage((record,))))
        try:
            for language in available_languages():
                set_language(language)
                for dark in (False, True):
                    self.app.setPalette(engine.qt_palette(dark=dark))
                    self.app.setStyleSheet(engine.application_stylesheet(dark=dark))
                    dialog = RecordSearchDialog(model, record.day, job_runner=ImmediateJobRunner())
                    try:
                        dialog.show()
                        for width, height in ((740, 500), (960, 600)):
                            dialog.resize(width, height)
                            self.app.processEvents()
                            self.assertEqual((dialog.width(), dialog.height()), (width, height))
                            for field in (dialog.search_input, dialog.start_input, dialog.end_input,
                                          dialog.type_combo, dialog.project_combo, dialog.item_combo,
                                          dialog.open_button, dialog.more_button, dialog.close_button):
                                if field.isVisible():
                                    self.assertTrue(dialog.rect().contains(field.rect().translated(field.mapTo(dialog, QPoint()))))
                            self.assertEqual(dialog.results.topLevelItemCount(), 1)
                            for mode in ("month", "year", "custom", "all"):
                                dialog.date_range.mode_input.setCurrentIndex(dialog.date_range.mode_input.findData(mode))
                                self.app.processEvents()
                                for field in (dialog.date_range.mode_input, dialog.date_range.period_button,
                                              dialog.start_input, dialog.end_input):
                                    if field.isVisible():
                                        self.assertTrue(dialog.rect().contains(field.rect().translated(field.mapTo(dialog, QPoint()))))
                            dialog.date_range.mode_input.setCurrentIndex(0)
                            self.app.processEvents()
                            target = os.environ.get("WORKLOGGER_SCREENSHOTS")
                            if target:
                                Path(target).mkdir(parents=True, exist_ok=True)
                                self.assertTrue(dialog.grab().save(str(Path(target) / f"{language}-record-search-{'dark' if dark else 'light'}-{width}.png")))
                    finally:
                        dialog.hide()
                        dialog.deleteLater()
        finally:
            self.app.setPalette(old_palette)
            self.app.setStyleSheet(old_style)

    def test_custom_type_manager_fits_long_names_and_accounting_controls(self):
        import tempfile
        from worklogger.app.use_cases.entry_types import EntryTypeService
        from worklogger.infrastructure.database import SQLiteConnectionFactory, MigrationRunner
        from worklogger.infrastructure.repositories import SQLiteAuthRepository
        from worklogger.infrastructure.repositories.entry_type_sqlite import SQLiteEntryTypeRepository
        from worklogger.infrastructure.security import PBKDF2PasswordHasher
        from worklogger.presentation.widgets.classification_manager import ClassificationManagerDialog
        from worklogger.presentation.theme import ThemeEngine, configure_application_style, install_bundled_fonts

        configure_application_style()
        install_bundled_fonts()

        with tempfile.TemporaryDirectory() as directory:
            factory = SQLiteConnectionFactory(Path(directory) / "types.db")
            MigrationRunner(factory).run_pending()
            user = SQLiteAuthRepository(factory, password_hasher=PBKDF2PasswordHasher(iterations=1000)).create_user(
                "sample", "example-password", recovery_key=None, is_admin=False)
            service = EntryTypeService(user.id, SQLiteEntryTypeRepository(factory))
            service.save("Research and development across international product teams", "work")
            service.save("Lunch", "break")
            service.save("Personal leave", "leave")

            class Model:
                def list_types(self):
                    return service.list_types()
                def save_type(self, label, category, previous=None):
                    return service.save(label, category, previous)
                def archive_type(self, definition):
                    return service.archive(definition)

            engine = ThemeEngine()
            for language, dark in (("en_US", False), ("zh_CN", True)):
                set_language(language)
                self.app.setPalette(engine.qt_palette(dark=dark))
                self.app.setStyleSheet(engine.application_stylesheet(dark=dark))
                dialog = ClassificationManagerDialog(Model())
                try:
                    dialog.show()
                    self.app.processEvents()
                    self.assertEqual((dialog.width(), dialog.height()), (700, 420))
                    dialog.type_list.setCurrentRow(0)
                    self.assertTrue(dialog.name_input.text())
                    for control in (dialog.type_list, dialog.name_input, dialog.category_combo,
                                    dialog.save_button, dialog.new_button, dialog.archive_button, dialog.close_button):
                        self.assertTrue(dialog.rect().contains(control.rect().translated(control.mapTo(dialog, QPoint()))))
                    destination = os.environ.get("WORKLOGGER_SCREENSHOTS")
                    if destination:
                        Path(destination).mkdir(parents=True, exist_ok=True)
                        self.assertTrue(dialog.grab().save(str(Path(destination) / f"{language}-work-types.png")))
                finally:
                    dialog.hide()
                    dialog.deleteLater()


    def test_last_day_is_accessible_without_shrinking_cells_or_right_panel(self):
        records, _events, _selected = may_records()
        window = _window(records)
        window._current_month = date(2026, 5, 1)
        window._selected_day = date(2026, 5, 1)
        window._holidays = {date(2026, 5, 31): "International Workers Memorial Day"}
        window.resize(880, 580)
        window.show()
        try:
            self.assertTrue(window.refresh())
            self.app.processEvents()
            self.assertTrue(window.select_day(date(2026, 5, 31)))
            self.app.processEvents()
            scroll = window.calendar_page.calendar_scroll
            self.assertGreater(scroll.verticalScrollBar().maximum(), 0)
            self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
            selected = next(button for button in window.calendar_view.day_buttons() if button.cell.is_selected)
            position = selected.mapTo(scroll.viewport(), QPoint())
            self.assertGreaterEqual(position.y(), 0)
            self.assertLessEqual(position.y() + selected.height(), scroll.viewport().height())
            self.assertGreaterEqual(selected.height(), 90)
            self.assertIn("International Workers Memorial Day", selected.toolTip())
            self.assertTrue(window.entry_panel.actions_widget.isVisibleTo(window.calendar_page))
            self.assertEqual((window.width(), window.height()), (880, 580))
        finally:
            window.close()


    def test_calendar_right_panel_fits_and_keeps_notes_and_records_accessible(self):
        records, events, selected = may_records()
        for language in available_languages():
            set_language(language)
            for dark in ((False, True) if language == "en_US" else (language in ("ja_JP", "zh_TW"),)):
                window = _window(records, account_name="Sample User", calendar_events=events)
                window._config = replace(window._config, dark=dark, selected_day=selected)
                window._selected_day = selected
                window._current_month = date(2026, 5, 1)
                window._today = date(2026, 5, 15)
                window._holidays = {date(2026, 5, 21): "International Workers Memorial Day"}
                window.apply_theme()
                window.calendar_view.set_loading(True)
                window.show()
                try:
                    sizes = ((880, 580), (1100, 700), (1800, 1000)) if language == "en_US" else ((880, 580),)
                    for width, height in sizes:
                        window.resize(width, height)
                        self.app.processEvents()
                        calendar = window.calendar_view
                        center = calendar.loading_label.mapTo(calendar, calendar.loading_label.rect().center())
                        self.assertLessEqual(abs(center.x() - calendar.rect().center().x()), 1)
                        self.assertLessEqual(abs(center.y() - calendar.rect().center().y()), 1)
                        self.assertTrue(calendar.loading_label.isVisible())
                        self.assertTrue(calendar.grid_frame.isHidden())
                        directory = os.environ.get("WORKLOGGER_SCREENSHOTS")
                        if directory:
                            target = Path(directory)
                            target.mkdir(parents=True, exist_ok=True)
                            self.assertTrue(window.grab().save(str(target /
                                f"{language}-calendar-loading-{'dark' if dark else 'light'}-{width}.png")))
                    self.assertTrue(window.refresh())
                    self.app.processEvents()
                    self.assertTrue(window.calendar_view.loading_label.isHidden())
                    self.assertTrue(window.calendar_view.grid_frame.isVisible())
                    for width, height in sizes:
                        with self.subTest(language=language, dark=dark, width=width):
                            window.resize(width, height)
                            self.app.processEvents()
                            self.assertEqual((window.width(), window.height()), (width, height))
                            panel = window.entry_panel
                            right = window.calendar_page.findChild(QFrame, "calendar_right_panel_frame")
                            self.assertGreater(window.calendar_page.calendar_scroll.width(), right.width())
                            self.assertLessEqual(right.width(), 380)
                            self.assertLessEqual(panel.content_input.mapTo(window.calendar_page, QPoint()).y(), 350)
                            if height >= 700:
                                self.assertLessEqual(panel.save_button.mapTo(window.calendar_page, QPoint()).y() - panel.hours_label.mapTo(window.calendar_page, QPoint()).y(), 60)
                            self.assertTrue(panel.content_input.isVisible())
                            fields = (panel.start_input, panel.end_input)
                            self.assertEqual(fields[0].mapTo(window, QPoint()).y(), fields[1].mapTo(window, QPoint()).y())
                            for field in fields:
                                rect = field.rect().translated(field.mapTo(panel.time_tabs.currentWidget(), QPoint()))
                                self.assertTrue(panel.time_tabs.currentWidget().rect().contains(rect))
                            for field in (*fields, panel.save_button, panel.clear_button, window.calendar_page.selected_date_label):
                                position = field.mapTo(window.calendar_page, QPoint())
                                self.assertGreaterEqual(position.y(), 0)
                                self.assertLessEqual(position.y() + field.height(), window.calendar_page.height())
                            self.assertEqual(window.calendar_page.details_scroll.horizontalScrollBar().maximum(), 0)
                            self.assertGreaterEqual(window.calendar_page.records_scroll.height(), 96)
                            self.assertEqual(sum(button.isVisible() for button in window.calendar_view.day_buttons()), 31)
                            self.assertTrue(all(button.height() >= 90 for button in window.calendar_view.day_buttons() if button.isVisible()))
                            self.assertEqual(window.calendar_page.calendar_scroll.horizontalScrollBar().maximum(), 0)
                            self.assertTrue(all(not label.isVisible() for label in window.calendar_view.week_total_labels()))
                            history = window.calendar_page.records_widget
                            self.assertEqual(len(history.event_buttons), sum(event.day == selected for event in events))
                            self.assertEqual(len(history.entry_buttons), 1)
                            directory = os.environ.get("WORKLOGGER_SCREENSHOTS")
                            if directory:
                                target = Path(directory)
                                target.mkdir(parents=True, exist_ok=True)
                                self.assertTrue(window.grab().save(str(target / f"{language}-calendar-may-{'dark' if dark else 'light'}-{width}.png")))
                            panel.time_tabs.setCurrentIndex(1)
                            self.app.processEvents()
                            self.assertTrue(panel.clock_in_button.isVisible())
                            for button in (panel.clock_in_button, panel.clock_out_button, panel.break_button, panel.discard_timer_button):
                                self.assertLessEqual(button.fontMetrics().horizontalAdvance(button.text()) + (24 if not button.icon().isNull() else 0) + 18, button.width())
                            self.assertTrue(panel.actions_widget.isVisible())
                            panel.time_tabs.setCurrentIndex(0)
                            self.app.processEvents()
                    if events:
                        self.assertTrue(window.select_day(events[0].day))
                        self.app.processEvents()
                        event_buttons = window.calendar_page.records_widget.event_buttons.values()
                        self.assertTrue(any(events[0].summary in button.label.text() for button in event_buttons))
                finally:
                    window.close()


if __name__ == "__main__":
    unittest.main()
