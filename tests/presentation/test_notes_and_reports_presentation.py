from __future__ import annotations

from datetime import date
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from tests.app.test_notes_and_reports_use_cases import (
    MemoryCalendarRepository,
    MemoryDailyNoteRepository,
    MemoryQuickLogRepository,
    MemoryTemplateProvider,
    MemoryTemplateRepository,
    MemoryWorkLogRepository,
)
from worklogger.app.commands.note_commands import SaveDailyNoteCommand
from worklogger.app.commands.report_commands import SaveReportCommand
from worklogger.app.queries.note_queries import GetDailyNoteQuery
from worklogger.app.queries.report_queries import GetReportForPeriodQuery
from worklogger.app.use_cases.calendar import GetCalendarEventsForDayHandler
from worklogger.app.use_cases.ai import RewriteTextHandler
from worklogger.app.use_cases.notes import GetDailyNoteHandler, SaveDailyNoteHandler
from worklogger.app.use_cases.quick_logs import GetQuickLogsForDayHandler
from worklogger.app.use_cases.reports import (
    GenerateReportHandler,
    ResetReportTemplateHandler,
    SaveReportTemplateHandler,
)
from worklogger.domain.calendar.models import CalendarEvent
from worklogger.domain.quicklog.models import QuickLog
from worklogger.domain.reporting.models import Report
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkLog, WorkType
from worklogger.infrastructure.export import MarkdownExporter
from worklogger.presentation.notes import NoteEditorDialog
from worklogger.presentation.reporting import ReportDialog
from worklogger.presentation.viewmodels import NoteEditorViewModel, ReportEditorViewModel


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

    def test_note_viewmodel_and_dialog_apply_template_insert_quicklogs_and_save(self) -> None:
        notes = MemoryDailyNoteRepository()
        quick_logs = MemoryQuickLogRepository(
            (
                QuickLog(
                    id=1,
                    user_id=1,
                    day=date(2026, 5, 14),
                    start_time="09:30",
                    end_time="10:00",
                    description="Standup",
                ),
            )
        )
        calendar = MemoryCalendarRepository(
            (
                CalendarEvent(
                    id=1,
                    user_id=1,
                    day=date(2026, 5, 14),
                    start_time="14:00",
                    end_time="15:00",
                    summary="Planning",
                ),
            )
        )
        template_repository = MemoryTemplateRepository()
        view_model = NoteEditorViewModel(
            user_id=1,
            get_note_handler=GetDailyNoteHandler(notes),
            save_note_handler=SaveDailyNoteHandler(notes),
            quick_logs_handler=GetQuickLogsForDayHandler(quick_logs),
            calendar_events_handler=GetCalendarEventsForDayHandler(calendar),
            templates=MemoryTemplateProvider(),
            save_template_handler=SaveReportTemplateHandler(template_repository),
            reset_template_handler=ResetReportTemplateHandler(template_repository),
            markdown_exporter=MarkdownExporter(),
            rewrite_handler=RewriteTextHandler(),
        )
        SaveDailyNoteHandler(notes).handle(
            SaveDailyNoteCommand(1, date(2026, 5, 14), "Existing note")
        )
        dialog = NoteEditorDialog(view_model, date(2026, 5, 14))

        self.assertTrue(dialog.refresh())
        self.assertEqual(dialog.editor.toPlainText(), "Existing note")
        self.assertIn("Planning", dialog.calendar_label.text())

        dialog.quick_logs_button.click()
        self.assertIn("Standup", dialog.editor.toPlainText())

        dialog.template_button.click()
        self.assertIn("Planning", dialog.editor.toPlainText())
        self.assertIn("Standup", dialog.editor.toPlainText())

        dialog.editor.setPlainText("Saved from dialog")
        dialog.save_button.click()

        self.assertEqual(
            notes.get_for_day(1, date(2026, 5, 14)).content,
            "Saved from dialog",
        )
        self.assertEqual(dialog.status_label.text(), "Saved")

        dialog.copy_button.click()
        self.assertEqual(QApplication.clipboard().text(), "Saved from dialog")
        with tempfile.TemporaryDirectory() as directory:
            exported = Path(directory) / "note"
            self.assertTrue(dialog.export_markdown(exported))
            self.assertEqual(exported.with_suffix(".md").read_text(encoding="utf-8"), "Saved from dialog")

        dialog.save_template_button.click()
        saved_template = template_repository.get(1, "en_US", "daily")
        self.assertIsNotNone(saved_template)
        assert saved_template is not None
        self.assertEqual(saved_template.content, "Saved from dialog")
        dialog.reset_template_button.click()
        self.assertIsNone(template_repository.get(1, "en_US", "daily"))

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
        notes = MemoryDailyNoteRepository()
        quick_logs = MemoryQuickLogRepository(())
        calendar = MemoryCalendarRepository(())
        template_repository = MemoryTemplateRepository()
        note_view_model = NoteEditorViewModel(
            user_id=1,
            get_note_handler=GetDailyNoteHandler(notes),
            save_note_handler=SaveDailyNoteHandler(notes),
            quick_logs_handler=GetQuickLogsForDayHandler(quick_logs),
            calendar_events_handler=GetCalendarEventsForDayHandler(calendar),
            templates=MemoryTemplateProvider(),
            save_template_handler=SaveReportTemplateHandler(template_repository),
            reset_template_handler=ResetReportTemplateHandler(template_repository),
            markdown_exporter=MarkdownExporter(),
            rewrite_handler=RewriteTextHandler(),
        )
        note_dialog = NoteEditorDialog(
            note_view_model,
            date(2026, 5, 14),
            confirm_discard_changes=lambda: False,
        )
        self.assertTrue(note_dialog.refresh())
        note_dialog.editor.setPlainText("dirty")
        note_dialog.reject()

        self.assertTrue(note_dialog.has_unsaved_changes)
        self.assertEqual(note_dialog.status_label.text(), "Unsaved changes")

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
