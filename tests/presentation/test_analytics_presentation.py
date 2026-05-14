from __future__ import annotations

from datetime import date
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from worklogger.app.commands.work_log_commands import SaveWorkLogCommand
from worklogger.app.use_cases.analytics import GetAnalyticsBundleHandler
from worklogger.app.use_cases.work_logs import SaveWorkLogHandler
from worklogger.domain.worklog.models import WorkLog, WorkType
from worklogger.infrastructure.export import AnalyticsCsvExporter, AnalyticsPdfExporter
from worklogger.presentation.analytics import AnalyticsDialog
from worklogger.presentation.viewmodels import AnalyticsViewModel
from worklogger.presentation.widgets import ComboChart


def _app() -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        return existing
    return QApplication([])


class MemoryWorkLogRepository:
    def __init__(self) -> None:
        self.records: dict[tuple[int, date], WorkLog] = {}

    def get_for_day(self, user_id: int, day: date) -> WorkLog | None:
        return self.records.get((user_id, day))

    def list_for_month(self, user_id: int, year: int, month: int) -> tuple[WorkLog, ...]:
        return tuple(
            record
            for (record_user_id, record_day), record in sorted(self.records.items())
            if record_user_id == user_id
            and record_day.year == year
            and record_day.month == month
        )

    def list_all(self, user_id: int) -> tuple[WorkLog, ...]:
        return tuple(
            record
            for (record_user_id, _day), record in sorted(self.records.items())
            if record_user_id == user_id
        )

    def save(self, work_log: WorkLog) -> None:
        self.records[(work_log.user_id, work_log.day)] = work_log

    def remove(self, user_id: int, day: date) -> None:
        self.records.pop((user_id, day), None)


class AnalyticsPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = _app()

    def test_analytics_dialog_loads_chart_and_exports_csv_pdf(self) -> None:
        repository = MemoryWorkLogRepository()
        save = SaveWorkLogHandler(repository)
        save.handle(
            SaveWorkLogCommand(
                user_id=1,
                day=date(2026, 5, 4),
                start_time="09:00",
                end_time="18:00",
                break_hours=1.0,
                note="Feature work",
                work_type=WorkType.NORMAL.value,
            )
        )
        save.handle(
            SaveWorkLogCommand(
                user_id=1,
                day=date(2026, 5, 5),
                start_time=None,
                end_time=None,
                break_hours=0.0,
                note="Leave",
                work_type=WorkType.PAID_LEAVE.value,
            )
        )
        view_model = AnalyticsViewModel(
            user_id=1,
            bundle_handler=GetAnalyticsBundleHandler(repository),
            csv_exporter=AnalyticsCsvExporter(),
            pdf_exporter=AnalyticsPdfExporter(),
        )
        dialog = AnalyticsDialog(view_model, date(2026, 5, 14))

        self.assertTrue(dialog.refresh())
        assert dialog._state is not None
        self.assertTrue(dialog._state.bundle.bar_data)
        self.assertIn("Total:", dialog.summary_label.text())

        dialog.chart_combo.setCurrentIndex(1)
        self.assertTrue(dialog.refresh())
        self.assertEqual(dialog._state.chart_mode, "line")

        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "analytics"
            pdf_path = Path(directory) / "analytics"
            self.assertTrue(dialog.export_csv(csv_path))
            self.assertTrue(dialog.export_pdf(pdf_path))
            self.assertIn("label,bar_value", csv_path.with_suffix(".csv").read_text(encoding="utf-8-sig"))
            self.assertTrue(pdf_path.with_suffix(".pdf").read_bytes().startswith(b"%PDF-"))

    def test_combo_chart_accepts_bar_and_line_modes(self) -> None:
        view_model = AnalyticsViewModel(
            user_id=1,
            bundle_handler=GetAnalyticsBundleHandler(MemoryWorkLogRepository()),
            csv_exporter=AnalyticsCsvExporter(),
            pdf_exporter=AnalyticsPdfExporter(),
        )
        state = view_model.load(year=2026, month=5)
        self.assertTrue(state.ok, state.error)
        assert state.value is not None

        chart = ComboChart()
        chart.resize(320, 240)
        chart.set_data(state.value.bundle, mode="bar")
        chart.set_data(state.value.bundle, mode="line")

        self.assertEqual(chart.objectName(), "combo_chart")


if __name__ == "__main__":
    unittest.main()
