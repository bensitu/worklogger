from __future__ import annotations

from dataclasses import replace
from datetime import date
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from worklogger.app.use_cases.quick_logs import (
    AddQuickLogHandler,
    DeleteQuickLogHandler,
    GetQuickLogsForDayHandler,
    UpdateQuickLogHandler,
)
from worklogger.domain.quicklog.models import QuickLog
from worklogger.presentation.quick_logs import QuickLogDialog
from worklogger.presentation.viewmodels import QuickLogEditorViewModel


def _app() -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        return existing
    return QApplication([])


class MemoryQuickLogRepository:
    def __init__(self) -> None:
        self.logs: list[QuickLog] = []
        self.next_id = 1

    def add(self, quick_log: QuickLog) -> QuickLog:
        saved = replace(quick_log, id=self.next_id)
        self.next_id += 1
        self.logs.append(saved)
        return saved

    def update(self, quick_log: QuickLog) -> None:
        self.logs = [
            quick_log
            if log.user_id == quick_log.user_id and log.id == quick_log.id
            else log
            for log in self.logs
        ]

    def remove(self, user_id: int, quick_log_id: int) -> None:
        self.logs = [
            log
            for log in self.logs
            if not (log.user_id == user_id and log.id == quick_log_id)
        ]

    def list_for_day(self, user_id: int, day: date) -> tuple[QuickLog, ...]:
        return tuple(
            log
            for log in self.logs
            if log.user_id == user_id and log.day == day
        )

    def list_for_range(
        self,
        user_id: int,
        start_day: date,
        end_day: date,
    ) -> tuple[QuickLog, ...]:
        return tuple(
            log
            for log in self.logs
            if log.user_id == user_id and start_day <= log.day <= end_day
        )


class QuickLogPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = _app()

    def test_quick_log_dialog_adds_updates_and_deletes_entries(self) -> None:
        repository = MemoryQuickLogRepository()
        view_model = QuickLogEditorViewModel(
            user_id=1,
            add_handler=AddQuickLogHandler(repository),
            update_handler=UpdateQuickLogHandler(repository),
            delete_handler=DeleteQuickLogHandler(repository),
            get_day_handler=GetQuickLogsForDayHandler(repository),
        )
        dialog = QuickLogDialog(view_model, date(2026, 5, 14))

        self.assertTrue(dialog.refresh())
        self.assertEqual(dialog.list_widget.count(), 0)

        dialog.start_input.setText("09:00")
        dialog.end_input.setText("09:30")
        dialog.description_input.setText("Standup")
        dialog.add_button.click()

        self.assertEqual(dialog.list_widget.count(), 1)
        self.assertIn("Standup", dialog.list_widget.item(0).text())
        self.assertEqual(dialog.status_label.text(), "Quick Log added.")

        dialog.description_input.setText("Daily standup")
        dialog.update_button.click()

        self.assertEqual(repository.logs[0].description, "Daily standup")
        self.assertEqual(dialog.status_label.text(), "Quick Log updated.")

        dialog.delete_button.click()

        self.assertEqual(repository.logs, [])
        self.assertEqual(dialog.list_widget.count(), 0)
        self.assertEqual(dialog.status_label.text(), "Quick Log deleted.")


if __name__ == "__main__":
    unittest.main()
