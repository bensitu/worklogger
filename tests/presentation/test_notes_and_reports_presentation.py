from __future__ import annotations

from datetime import date
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
from worklogger.domain.reporting.models import Report
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkLog, WorkType
from worklogger.infrastructure.export import MarkdownExporter
from worklogger.presentation.notes import NoteEditorDialog
from worklogger.presentation.reporting import ReportDialog
from worklogger.presentation.viewmodels import NoteEditorViewModel, ReportEditorViewModel
from worklogger.presentation.job_runner import ImmediateJobRunner
from worklogger.infrastructure.database import MigrationRunner, SQLiteConnectionFactory
from worklogger.infrastructure.repositories import SQLiteAuthRepository, SQLiteDailyNoteRepository, SQLiteQuickLogRepository, SQLiteSettingsRepository
from worklogger.infrastructure.security import PBKDF2PasswordHasher
from worklogger.domain.notes.models import DailyNote
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
        return NoteEditorViewModel(service, markdown_exporter=MarkdownExporter(), rewrite_handler=RewriteTextHandler()), notes, quick

    def test_memos_preserve_previous_entries_drafts_and_sharing_choices(self):
        model, notes, quick = self._note_model()
        day = date(2026, 5, 14)
        quick.add(QuickLog(None, model.service.user_id, day, "Standup", "09:30", "10:00"))
        notes.save(DailyNote(model.service.user_id, day, "Existing note"))
        dialog = NoteEditorDialog(model, day, job_runner=ImmediateJobRunner())
        self.addCleanup(dialog.deleteLater)
        self.assertTrue(dialog.refresh())
        self.assertEqual(dialog.editor.toPlainText(), "Existing note")
        self.assertFalse(dialog.report_checkbox.isChecked())
        self.assertFalse(dialog.ai_checkbox.isChecked())
        self.assertEqual(dialog.previous_list.count(), 1)
        dialog.insert_button.click()
        first = dialog.editor.toPlainText()
        dialog.insert_button.click()
        self.assertEqual(dialog.editor.toPlainText(), first)
        self.assertIn("Standup", first)
        self.assertEqual(len(quick.list_for_day(model.service.user_id, day)), 1)
        dialog.editor.setPlainText("Recoverable draft")
        dialog.report_checkbox.setChecked(True)
        dialog._persist_draft()
        restored = NoteEditorDialog(model, day, job_runner=ImmediateJobRunner())
        self.addCleanup(restored.deleteLater)
        self.assertTrue(restored.refresh())
        self.assertEqual(restored.editor.toPlainText(), "Recoverable draft")
        self.assertTrue(restored._state.recovered_draft)
        self.assertTrue(restored.report_checkbox.isChecked())
        with patch.object(QMessageBox, "information"):
            restored.save_button.click()
        self.assertEqual(notes.get_for_day(model.service.user_id, day).content, "Recoverable draft")
        self.assertFalse(model.load(day).value.recovered_draft)
        self.assertTrue(model.load(day).value.sharing.reports)
        self.assertFalse(model.load(day).value.sharing.ai)
        self.assertEqual(model.search("Standup").value[0].day, day)
        restored.copy_button.click()
        self.assertEqual(QApplication.clipboard().text(), "Recoverable draft")
        with tempfile.TemporaryDirectory() as directory, patch.object(QMessageBox, "information"):
            target = Path(directory) / "note"
            restored.export_markdown(target)
            self.assertEqual(target.with_suffix(".md").read_text(encoding="utf-8"), "Recoverable draft")
        dialog._draft_timer.stop()
        restored._draft_timer.stop()

    def test_memo_conflicts_and_cancelled_close_keep_the_draft(self):
        model, notes, _quick = self._note_model()
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
        model, notes, _quick = self._note_model()
        saved_day, empty_day = date(2026, 10, 8), date(2026, 10, 9)
        notes.save(DailyNote(model.service.user_id, saved_day, "Meeting summary\nFollow up tomorrow"))
        dialog = NoteEditorDialog(model, empty_day, job_runner=ImmediateJobRunner())
        self.addCleanup(dialog.deleteLater)
        self.assertTrue(dialog.refresh())
        self.assertEqual(dialog.editor.toPlainText(), "")
        self.assertTrue(dialog.editor.placeholderText())
        self.assertFalse(dialog.copy_button.isEnabled())
        self.assertFalse(dialog.export_button.isEnabled())
        self.assertFalse(dialog.rewrite_button.isEnabled())
        self.assertEqual(dialog.history_list.currentItem().data(Qt.ItemDataRole.UserRole), empty_day)
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
        self.assertEqual(dialog.editor.toPlainText(), "")
        self.assertFalse(dialog.copy_button.isEnabled())
        dialog.search_input.setText("no matching content")
        dialog._search()
        self.assertEqual(dialog.history_list.count(), 0)
        self.assertFalse(dialog.empty_label.isHidden())
        self.assertEqual(dialog._day, empty_day)
        dialog._draft_timer.stop()
        dialog._search_timer.stop()

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
        note_view_model, _notes, _quick = self._note_model()
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
