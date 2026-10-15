from __future__ import annotations

from datetime import date, timedelta
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QDate, QLocale, Qt

from tests.app.test_notes_and_reports_use_cases import (
    MemoryCalendarRepository,
    MemoryQuickLogRepository,
    MemoryTemplateProvider,
    MemoryTemplateRepository,
    MemoryWorkLogRepository,
)
from worklogger.app.commands.report_commands import SaveReportCommand
from worklogger.app.queries.report_queries import GetReportForPeriodQuery
from worklogger.app.use_cases.ai import RewriteTextHandler
from worklogger.app.use_cases.notes import DailyNotesService
from worklogger.app.use_cases.reports import (
    GenerateReportHandler,
    ResetReportTemplateHandler,
    SaveReportTemplateHandler,
)
from worklogger.domain.quicklog.models import QuickLog
from tests.quick_log_samples import insert_previous_entry
from worklogger.domain.reporting.models import Report
from worklogger.domain.shared.result import Result
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.worklog.models import WorkLog, WorkType
from worklogger.infrastructure.export import MarkdownExporter
from worklogger.presentation.notes import NoteEditorDialog
from worklogger.presentation.reporting import ReportDialog
from worklogger.presentation.viewmodels import NoteEditorViewModel, ReportEditorViewModel
from worklogger.presentation.job_runner import ImmediateJobRunner
from worklogger.infrastructure.database import MigrationRunner, SQLiteConnectionFactory
from worklogger.infrastructure.repositories import SQLiteAuthRepository, SQLiteDailyNoteRepository, SQLiteQuickLogRepository, SQLiteSettingsRepository
from worklogger.infrastructure.security import PBKDF2PasswordHasher
from worklogger.domain.notes.models import DailyNote, NoteHistoryFilter
from worklogger.infrastructure.i18n import get_language


def _app() -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        return existing
    return QApplication([])


class MemoryReportRepository:
    def __init__(self) -> None:
        self.reports: list[Report] = []

    def save(self, report: Report) -> Report:
        saved = Report(
            id=len(self.reports) + 1,
            user_id=report.user_id,
            report_type=report.report_type,
            period_start=report.period_start,
            period_end=report.period_end,
            content=report.content,
        )
        self.reports.append(saved)
        return saved

    def get_for_period(
        self,
        user_id: int,
        report_type: str,
        period_start: date,
        period_end: date,
    ) -> Report | None:
        for report in reversed(self.reports):
            if (
                report.user_id == user_id
                and report.report_type == report_type
                and report.period_start == period_start
                and report.period_end == period_end
            ):
                return report
        return None

    def list_by_type(self, user_id: int, report_type: str) -> tuple[Report, ...]:
        return tuple(
            report
            for report in self.reports
            if report.user_id == user_id and report.report_type == report_type
        )

    def remove(self, user_id: int, report_id: int) -> None:
        self.reports = [
            report
            for report in self.reports
            if not (report.user_id == user_id and report.id == report_id)
        ]


class GetReportHandler:
    def __init__(self, repository: MemoryReportRepository) -> None:
        self.repository = repository

    def handle(self, query: GetReportForPeriodQuery) -> Result[Report | None]:
        return Result.success(
            self.repository.get_for_period(
                query.user_id,
                query.report_type,
                query.period_start,
                query.period_end,
            )
        )


class SaveReportHandler:
    def __init__(self, repository: MemoryReportRepository) -> None:
        self.repository = repository

    def handle(self, command: SaveReportCommand) -> Result[Report]:
        return Result.success(
            self.repository.save(
                Report(
                    id=None,
                    user_id=command.user_id,
                    report_type=command.report_type,
                    period_start=command.period_start,
                    period_end=command.period_end,
                    content=command.content,
                )
            )
        )


class NotesReportsPresentationTests(unittest.TestCase):
    def setUp(self):
        from tests.presentation.qt_support import dispose_test_windows
        self.addCleanup(dispose_test_windows)

    @classmethod
    def setUpClass(cls) -> None:
        cls._app = _app()

    def _note_model(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        factory = SQLiteConnectionFactory(root / "notes.db")
        MigrationRunner(factory).run_pending()
        auth = SQLiteAuthRepository(factory, password_hasher=PBKDF2PasswordHasher(iterations=1000))
        user = auth.create_user("memo.user", "example-password", recovery_key=None, is_admin=False)
        notes, quick = SQLiteDailyNoteRepository(factory), SQLiteQuickLogRepository(factory)
        service = DailyNotesService(user_id=user.id, notes=notes, settings=SQLiteSettingsRepository(factory), previous_entries=quick)
        return NoteEditorViewModel(service, markdown_exporter=MarkdownExporter(), rewrite_handler=RewriteTextHandler()), notes, quick, factory

    def test_memos_preserve_previous_entries_drafts_and_sharing_choices(self):
        model, notes, quick, factory = self._note_model()
        day = date(2026, 5, 14)
        insert_previous_entry(factory, QuickLog(None, model.service.user_id, day, "Standup", "09:30", "10:00"))
        notes.save(DailyNote(model.service.user_id, day, "Existing note"))
        dialog = NoteEditorDialog(model, day, job_runner=ImmediateJobRunner())
        self.addCleanup(dialog.deleteLater)
        self.assertTrue(dialog.refresh())
        self.assertEqual(dialog.editor.toPlainText(), "Existing note")
        self.assertFalse(dialog.report_checkbox.isChecked())
        self.assertFalse(dialog.ai_checkbox.isChecked())
        self.assertEqual(dialog.previous_list.count(), 1)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            dialog.insert_button.click()
        self.assertEqual(dialog.editor.toPlainText(), "Existing note")
        self.assertEqual(len(quick.list_for_day(model.service.user_id, day)), 1)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
                patch("worklogger.presentation.notes.dialog.show_information"):
            dialog.insert_button.click()
        first = dialog.editor.toPlainText()
        dialog.insert_button.click()
        self.assertEqual(dialog.editor.toPlainText(), first)
        self.assertIn("Standup", first)
        self.assertEqual(len(quick.list_for_day(model.service.user_id, day)), 0)
        self.assertTrue(dialog.previous_group.isHidden())
        self.assertEqual(notes.get_for_day(model.service.user_id, day).content, first)
        dialog.editor.setPlainText("Recoverable draft")
        dialog.report_checkbox.setChecked(True)
        dialog._persist_draft()
        restored = NoteEditorDialog(model, day, job_runner=ImmediateJobRunner())
        self.addCleanup(restored.deleteLater)
        self.assertTrue(restored.refresh())
        self.assertEqual(restored.editor.toPlainText(), "Recoverable draft")
        self.assertTrue(restored._state.recovered_draft)
        self.assertTrue(restored.report_checkbox.isChecked())
        with patch("worklogger.presentation.notes.dialog.show_information"):
            restored.save_button.click()
        self.assertEqual(notes.get_for_day(model.service.user_id, day).content, "Recoverable draft")
        self.assertFalse(model.load(day).value.recovered_draft)
        self.assertTrue(model.load(day).value.sharing.reports)
        self.assertFalse(model.load(day).value.sharing.ai)
        self.assertEqual(model.browse(NoteHistoryFilter(text="Recoverable")).value.notes[0].day, day)
        restored.copy_button.click()
        self.assertEqual(QApplication.clipboard().text(), "Recoverable draft")
        with tempfile.TemporaryDirectory() as directory, patch("worklogger.presentation.notes.dialog.show_information"):
            target = Path(directory) / "note"
            restored.export_markdown(target)
            self.assertEqual(target.with_suffix(".md").read_text(encoding="utf-8"), "Recoverable draft")
        dialog._draft_timer.stop()
        restored._draft_timer.stop()

    def test_memo_conflicts_and_cancelled_close_keep_the_draft(self):
        model, notes, _quick, _factory = self._note_model()
        day = date(2026, 5, 14)
        notes.save(DailyNote(model.service.user_id, day, "Original"))
        dialog = NoteEditorDialog(model, day, job_runner=ImmediateJobRunner())
        self.addCleanup(dialog.deleteLater)
        self.assertTrue(dialog.refresh())
        dialog.editor.setPlainText("Unsubmitted")
        notes.save(DailyNote(model.service.user_id, day, "Changed elsewhere"))
        with patch.object(QMessageBox, "warning"):
            dialog.save_button.click()
        self.assertEqual(dialog.last_error.code, "note_conflict")
        self.assertEqual(dialog.editor.toPlainText(), "Unsubmitted")
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Cancel):
            dialog.reject()
        self.assertTrue(dialog.has_unsaved_changes)
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Save):
            dialog.reject()
        recovered = model.load(day).value
        self.assertEqual((recovered.content, recovered.expected_content), ("Unsubmitted", "Original"))
        self.assertEqual(notes.get_for_day(model.service.user_id, day).content, "Changed elsewhere")
        dialog._draft_timer.stop()

    def test_note_navigation_keeps_date_selection_and_content_actions_in_sync(self):
        model, notes, _quick, _factory = self._note_model()
        saved_day, other_day, empty_day = date(2026, 10, 8), date(2026, 10, 9), date(2026, 10, 10)
        notes.save(DailyNote(model.service.user_id, saved_day, "Meeting summary\nFollow up tomorrow"))
        notes.save(DailyNote(model.service.user_id, other_day, "Another note"))
        dialog = NoteEditorDialog(model, empty_day, job_runner=ImmediateJobRunner())
        self.addCleanup(dialog.deleteLater)
        self.assertTrue(dialog.refresh())
        self.assertEqual(dialog.editor.toPlainText(), "")
        self.assertTrue(dialog.editor.placeholderText())
        self.assertFalse(dialog.copy_button.isEnabled())
        self.assertFalse(dialog.export_button.isEnabled())
        self.assertFalse(dialog.rewrite_button.isEnabled())
        self.assertIsNone(dialog.history_list.currentItem())
        saved_item = dialog.history_list.item(1)
        dialog.history_list.setCurrentItem(saved_item)
        self.assertEqual(dialog.editor.toPlainText(), "Meeting summary\nFollow up tomorrow")
        self.assertEqual(dialog.date_label.text(), QLocale(get_language()).toString(
            QDate(2026, 10, 8), QLocale.FormatType.LongFormat))
        self.assertEqual(dialog.history_list.currentItem().data(Qt.ItemDataRole.UserRole), saved_day)
        self.assertTrue(dialog.copy_button.isEnabled())
        self.assertTrue(dialog.export_button.isEnabled())
        dialog.editor.setPlainText("Keep this draft")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            dialog.history_list.setCurrentItem(dialog.history_list.item(0))
        self.assertEqual(dialog.editor.toPlainText(), "Keep this draft")
        self.assertEqual(dialog.history_list.currentItem().data(Qt.ItemDataRole.UserRole), saved_day)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            dialog.history_list.setCurrentItem(dialog.history_list.item(0))
        self.assertEqual(model.load(saved_day).value.content, "Keep this draft")
        self.assertEqual(dialog.editor.toPlainText(), "Another note")
        self.assertTrue(dialog.copy_button.isEnabled())
        dialog.search_input.setText("no matching content")
        dialog.history_browser.refresh()
        self.assertEqual(dialog.history_list.count(), 0)
        self.assertFalse(dialog.empty_label.isHidden())
        self.assertEqual(dialog._day, other_day)
        dialog._draft_timer.stop()
        dialog.history_browser.stop()

    def test_search_keeps_inputs_available_and_discards_obsolete_results(self):
        model, notes, _quick, _factory = self._note_model()
        day = date(2026, 10, 9)
        notes.save(DailyNote(model.service.user_id, day, "Planning and meeting"))
        for offset in range(55):
            notes.save(DailyNote(model.service.user_id, date(2026, 1, 1) + timedelta(days=offset), "Archived note"))

        class DeferredSearchRunner(ImmediateJobRunner):
            def __init__(self):
                self.pending = []

            def submit(self, name, job, *, on_complete=None):
                if name == "search_notes":
                    self.pending.append((job, on_complete))
                    return None
                return super().submit(name, job, on_complete=on_complete)

            def complete(self, result=None):
                job, callback = self.pending.pop(0)
                callback(job(None) if result is None else result)

        runner = DeferredSearchRunner()
        dialog = NoteEditorDialog(model, day, job_runner=runner)
        self.addCleanup(dialog.deleteLater)
        self.assertTrue(dialog.refresh())
        browser = dialog.history_browser
        self.assertFalse(browser.loading_bar.isHidden())
        runner.complete()
        self.assertTrue(browser.loading_bar.isHidden())
        dialog.editor.setPlainText("Keep the current draft")
        dialog.search_input.setText("Planning")
        dialog.history_browser.refresh()
        self.assertTrue(dialog.search_input.isEnabled())
        self.assertTrue(dialog.editor.isEnabled())
        self.assertTrue(dialog._draft_timer.isActive())
        dialog.search_input.setText("no matching content")
        runner.complete()
        self.assertEqual(dialog.history_list.count(), 1)
        dialog.history_browser.refresh()
        runner.complete()
        self.assertEqual(dialog.history_list.count(), 0)
        self.assertEqual(dialog.editor.toPlainText(), "Keep the current draft")
        self.assertEqual(dialog._day, day)
        dialog.search_input.setText("Planning")
        dialog.history_browser.refresh()
        with patch.object(QMessageBox, "warning"):
            runner.complete(Result.failure(InfrastructureError("note_load_failed", "note_load_failed")))
        self.assertEqual(dialog.last_error.code, "note_load_failed")
        self.assertTrue(browser.loading_bar.isHidden())
        self.assertEqual(dialog.editor.toPlainText(), "Keep the current draft")
        dialog.history_browser.refresh()
        runner.complete()
        self.assertEqual(dialog.history_list.count(), 1)
        dialog.search_input.clear()
        browser.mode_input.setCurrentIndex(browser.mode_input.findData("all"))
        browser.refresh()
        self.assertFalse(browser.loading_bar.isHidden())
        self.assertTrue(browser.mode_input.isEnabled())
        self.assertTrue(dialog.editor.isEnabled())
        runner.complete()
        self.assertEqual(browser.history_list.count(), 50)
        browser.more_button.click()
        self.assertFalse(browser.loading_bar.isHidden())
        self.assertFalse(browser.more_button.isEnabled())
        self.assertEqual(browser.history_list.count(), 50)
        runner.complete()
        self.assertTrue(browser.loading_bar.isHidden())
        self.assertEqual(browser.history_list.count(), 56)
        self.assertTrue(browser.more_button.isHidden())
        dialog.search_input.setText("Planning")
        browser.refresh()
        browser.mode_input.setCurrentIndex(browser.mode_input.findData("custom"))
        self.assertTrue(browser.start_input.isEnabled())
        self.assertTrue(browser.end_input.isEnabled())
        runner.complete()
        self.assertEqual(browser.history_list.count(), 56)
        browser.refresh()
        runner.complete()
        self.assertEqual(browser.history_list.count(), 1)
        self.assertEqual(dialog.editor.toPlainText(), "Keep the current draft")
        dialog.search_input.clear()
        dialog.history_browser.refresh()
        dialog.history_browser.stop()
        runner.complete()
        self.assertFalse(dialog.history_browser._timer.isActive())
        self.assertTrue(browser.loading_bar.isHidden())
        dialog._draft_timer.stop()

    def test_note_history_ranges_search_and_pagination_preserve_the_editor(self):
        model, notes, quick, factory = self._note_model()
        day = date(2024, 2, 29)
        for offset in range(90):
            note_day = date(2024, 1, 1) + timedelta(days=offset)
            notes.save(DailyNote(model.service.user_id, note_day, "Meeting notes"))
        notes.save(DailyNote(model.service.user_id, date(2023, 12, 31), "Older meeting"))
        insert_previous_entry(factory, QuickLog(None, model.service.user_id, date(2023, 12, 30), "Previous meeting"))
        dialog = NoteEditorDialog(model, day, job_runner=ImmediateJobRunner())
        self.addCleanup(dialog.deleteLater)
        self.assertTrue(dialog.refresh())
        browser = dialog.history_browser
        self.assertEqual(browser.history_list.count(), 29)
        self.assertEqual(browser.history_list.currentItem().data(Qt.ItemDataRole.UserRole), day)
        browser.search_input.setText("Older")
        browser.refresh()
        self.assertEqual(browser.history_list.count(), 0)
        browser.mode_input.setCurrentIndex(browser.mode_input.findData("all"))
        browser.refresh()
        self.assertEqual(browser.history_list.count(), 1)
        browser.search_input.clear()
        browser.mode_input.setCurrentIndex(browser.mode_input.findData("month"))
        browser.refresh()
        self.assertEqual(browser.history_list.count(), 29)
        dialog.editor.setPlainText("Unfinished work")
        browser.previous_button.click()
        browser.refresh()
        self.assertEqual(browser.history_list.count(), 31)
        self.assertIsNone(browser.history_list.currentItem())
        browser.next_button.click()
        browser.refresh()
        self.assertEqual(browser.history_list.count(), 29)
        browser.mode_input.setCurrentIndex(browser.mode_input.findData("year"))
        browser.refresh()
        self.assertEqual(browser.history_list.count(), 50)
        self.assertFalse(browser.more_button.isHidden())
        browser.more_button.click()
        self.assertEqual(browser.history_list.count(), 90)
        self.assertTrue(browser.more_button.isHidden())
        self.assertEqual(len({browser.history_list.item(row).data(Qt.ItemDataRole.UserRole)
                              for row in range(90)}), 90)
        browser.mode_input.setCurrentIndex(browser.mode_input.findData("custom"))
        browser.start_input.setDate(date(2023, 12, 30))
        browser.end_input.setDate(date(2023, 12, 31))
        browser.refresh()
        self.assertEqual(browser.history_list.count(), 2)
        browser.start_input.setDate(date(2024, 1, 1))
        browser.refresh()
        self.assertEqual(browser.history_list.count(), 0)
        self.assertTrue(browser.more_button.isHidden())
        browser.mode_input.setCurrentIndex(browser.mode_input.findData("month"))
        browser.search_input.setText("Older")
        browser.refresh()
        self.assertEqual(browser.history_list.count(), 0)
        browser.mode_input.setCurrentIndex(browser.mode_input.findData("all"))
        browser.refresh()
        self.assertEqual(browser.history_list.count(), 1)
        browser.search_input.clear()
        browser.refresh()
        self.assertEqual(browser.history_list.count(), 50)
        self.assertEqual(browser.mode_input.currentData(), "all")
        self.assertTrue(browser.mode_input.isEnabled())
        browser.more_button.click()
        self.assertEqual(browser.history_list.count(), 92)
        self.assertEqual(dialog.editor.toPlainText(), "Unfinished work")
        self.assertEqual(dialog._day, day)
        browser.stop()
        dialog._draft_timer.stop()

    def test_report_viewmodel_and_dialog_generate_then_save_report(self) -> None:
        reports = MemoryReportRepository()
        work_logs = MemoryWorkLogRepository(
            (
                WorkLog(
                    user_id=1,
                    day=date(2026, 5, 11),
                    start_time="09:00",
                    end_time="18:00",
                    break_hours=1.0,
                    note="Report work",
                    work_type=WorkType.NORMAL,
                ),
            )
        )
        quick_logs = MemoryQuickLogRepository(())
        calendar = MemoryCalendarRepository(())
        template_repository = MemoryTemplateRepository()
        view_model = ReportEditorViewModel(
            user_id=1,
            generate_handler=GenerateReportHandler(
                work_logs=work_logs,
                quick_logs=quick_logs,
                calendar_events=calendar,
                templates=MemoryTemplateProvider(),
            ),
            get_report_handler=GetReportHandler(reports),
            save_report_handler=SaveReportHandler(reports),
            save_template_handler=SaveReportTemplateHandler(template_repository),
            reset_template_handler=ResetReportTemplateHandler(template_repository),
            markdown_exporter=MarkdownExporter(),
            rewrite_handler=RewriteTextHandler(),
        )
        dialog = ReportDialog(view_model, date(2026, 5, 11))

        self.assertTrue(dialog.refresh())
        self.assertIn("Report work", dialog.daily_editor.toPlainText())
        self.assertIn("Report work", dialog.weekly_editor.toPlainText())

        dialog.tabs.setCurrentIndex(1)
        dialog.weekly_editor.setPlainText("Saved weekly report")
        dialog.save_button.click()

        self.assertEqual(dialog.status_label.text(), "Report saved.")
        self.assertEqual(reports.reports[-1].content, "Saved weekly report")

        dialog.copy_button.click()
        self.assertEqual(QApplication.clipboard().text(), "Saved weekly report")
        with tempfile.TemporaryDirectory() as directory:
            exported = Path(directory) / "weekly-report"
            self.assertTrue(dialog.export_markdown(exported))
            self.assertEqual(
                exported.with_suffix(".md").read_text(encoding="utf-8"),
                "Saved weekly report",
            )

        dialog.save_template_button.click()
        saved_template = template_repository.get(1, "en_US", "weekly")
        self.assertIsNotNone(saved_template)
        dialog.reset_template_button.click()
        self.assertIsNone(template_repository.get(1, "en_US", "weekly"))

    def test_note_and_report_dialogs_block_close_when_dirty_prompt_is_cancelled(self) -> None:
        quick_logs = MemoryQuickLogRepository(())
        calendar = MemoryCalendarRepository(())
        template_repository = MemoryTemplateRepository()
        note_view_model, _notes, _quick, _factory = self._note_model()
        note_dialog = NoteEditorDialog(note_view_model, date(2026, 5, 14),
            confirm_discard_changes=lambda: False, job_runner=ImmediateJobRunner())
        self.addCleanup(note_dialog.deleteLater)
        self.assertTrue(note_dialog.refresh())
        note_dialog.editor.setPlainText("dirty")
        note_dialog.reject()
        self.assertTrue(note_dialog.has_unsaved_changes)
        note_dialog._draft_timer.stop()

        reports = MemoryReportRepository()
        report_view_model = ReportEditorViewModel(
            user_id=1,
            generate_handler=GenerateReportHandler(
                work_logs=MemoryWorkLogRepository(()),
                quick_logs=quick_logs,
                calendar_events=calendar,
                templates=MemoryTemplateProvider(),
            ),
            get_report_handler=GetReportHandler(reports),
            save_report_handler=SaveReportHandler(reports),
            save_template_handler=SaveReportTemplateHandler(template_repository),
            reset_template_handler=ResetReportTemplateHandler(template_repository),
            markdown_exporter=MarkdownExporter(),
            rewrite_handler=RewriteTextHandler(),
        )
        report_dialog = ReportDialog(
            report_view_model,
            date(2026, 5, 11),
            confirm_discard_changes=lambda: False,
        )
        self.assertTrue(report_dialog.refresh())
        report_dialog.daily_editor.setPlainText("dirty")
        report_dialog.reject()

        self.assertTrue(report_dialog.has_unsaved_changes)
        self.assertEqual(report_dialog.status_label.text(), "Unsaved changes")


if __name__ == "__main__":
    unittest.main()
