from __future__ import annotations

from datetime import date
import os
from pathlib import Path
import tempfile
import unittest
import unicodedata

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtPdf import QPdfDocument

from worklogger.app.commands.work_log_commands import SaveWorkLogCommand
from worklogger.app.use_cases.analytics import GetAnalyticsBundleHandler, GetAnalyticsDashboardHandler
from worklogger.app.use_cases.work_logs import SaveWorkLogHandler
from worklogger.domain.worklog.models import WorkLog, WorkType
from worklogger.domain.analytics.models import ChartDataBundle
from worklogger.infrastructure.export import AnalyticsCsvExporter, AnalyticsPdfExporter
from worklogger.infrastructure.i18n import set_language
from worklogger.presentation.analytics import AnalyticsDialog
from worklogger.presentation.date_labels import month_name
from worklogger.presentation.shell.pages import AnalyticsPage
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

    def save(self, work_log: WorkLog, *, expected_note: str | None = None) -> None:
        self.records[(work_log.user_id, work_log.day)] = work_log

    def remove(self, user_id: int, day: date) -> None:
        self.records.pop((user_id, day), None)


class AnalyticsPresentationTests(unittest.TestCase):
    def test_pdf_export_preserves_unicode_and_all_summary_rows(self):
        bundle = ChartDataBundle(bar_data=tuple((f"Work {index}", 8.0) for index in range(100)), line_data=(),
                                 leave_indices=(), leave_line_data=(), leave_hours_data=())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "summary.pdf"
            exported = AnalyticsPdfExporter().export_bundle(path, bundle, title="Work / 工作 / 勤務")
            self.assertTrue(exported.ok, exported.error)
            document = QPdfDocument()
            self.assertEqual(document.load(str(path)), QPdfDocument.Error.None_)
            try:
                self.assertGreater(document.pageCount(), 1)
                text = "\n".join(document.getAllText(page).text() for page in range(document.pageCount()))
            finally:
                document.close()
                del document
            normalized = "".join(unicodedata.normalize("NFKC", text).split())
            self.assertIn("工作", normalized)
            self.assertIn("勤務", normalized)
            self.assertIn("Work99", normalized)

    @classmethod
    def setUpClass(cls) -> None:
        cls._app = _app()
        from worklogger.presentation.theme.fonts import install_bundled_fonts
        install_bundled_fonts()

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

        self.assertEqual(chart.objectName(), "combo_chart_widget")

    def test_historical_period_switching_keeps_current_periods_selectable(self) -> None:
        today = date.today()
        scopes = ("monthly", "quarterly", "annual")

        def period_start(day, scope):
            month = 1 if scope == "annual" else ((day.month - 1) // 3 * 3 + 1 if scope == "quarterly" else day.month)
            return date(day.year, month, 1)

        for source in scopes:
            for destination in scopes:
                if source == destination:
                    continue
                with self.subTest(source=source, destination=destination):
                    repository = MemoryWorkLogRepository()
                    model = AnalyticsViewModel(
                        user_id=1, bundle_handler=GetAnalyticsBundleHandler(repository),
                        dashboard_handler=GetAnalyticsDashboardHandler(repository),
                        csv_exporter=AnalyticsCsvExporter(), pdf_exporter=AnalyticsPdfExporter(),
                    )
                    page = AnalyticsPage(model, today)
                    try:
                        page.scope_control.set_value(source)
                        page.period_combo.setCurrentIndex(page.period_combo.count() - 1)
                        historical = page.period_combo.currentData()
                        self.assertLess(historical, today.replace(day=1))
                        page.scope_control.set_value(destination)
                        values = [page.period_combo.itemData(index) for index in range(page.period_combo.count())]
                        current = period_start(today, destination)
                        self.assertIn(current, values)
                        self.assertEqual(values, sorted(set(values), reverse=True))
                        self.assertEqual(page.period_combo.currentData(), period_start(historical, destination))
                        self.assertEqual(page._dashboard.period_start, period_start(historical, destination))
                        page.period_combo.setCurrentIndex(values.index(current))
                        self.assertEqual(page._dashboard.period_start, current)
                        self.assertEqual(page._selected_day, current)
                    finally:
                        page.close()
                        page.deleteLater()
                        self._app.processEvents()

    def test_daily_average_chart_uses_localized_scope_specific_points(self) -> None:
        repository = MemoryWorkLogRepository()
        for month in (1, 4, 7, 12):
            repository.save(WorkLog(1, date(2026, month, 5), "09:00", "17:00", 0, "", WorkType.NORMAL))
        model = AnalyticsViewModel(
            user_id=1, bundle_handler=GetAnalyticsBundleHandler(repository),
            dashboard_handler=GetAnalyticsDashboardHandler(repository),
            csv_exporter=AnalyticsCsvExporter(), pdf_exporter=AnalyticsPdfExporter(),
        )
        for language, quarter_label in (("en_US", "Q1"), ("ja_JP", "第1四半期"), ("ko_KR", "1분기"),
                                         ("zh_CN", "第1季度"), ("zh_TW", "第1季")):
            set_language(language)
            page = AnalyticsPage(model, date(2026, 5, 14))
            try:
                for scope, count in (("monthly", 6), ("quarterly", 4), ("annual", 12)):
                    page.scope_control.set_value(scope)
                    self.assertTrue(page.refresh())
                    chart = page.daily_average_chart.chart
                    data = chart._bundle.line_data
                    with self.subTest(language=language, scope=scope):
                        self.assertEqual(len(data), count)
                        self.assertEqual(chart._mode, "line")
                        self.assertTrue(chart._average)
                        if scope == "quarterly":
                            self.assertEqual(data[0], (quarter_label, 8))
                            self.assertEqual(tuple(value for label, value in data), (8, 8, 8, 8))
                        else:
                            first_month, last_month = (12, 5) if scope == "monthly" else (1, 12)
                            self.assertEqual(data[0][0], month_name(date(2000, first_month, 1)))
                            self.assertEqual(data[-1][0], month_name(date(2000, last_month, 1)))
                        self.assertEqual(page.daily_average_value_label.text(), "8h 0m" if scope != "monthly" else "0h 0m")
            finally:
                page.close()
                page.deleteLater()
                self._app.processEvents()
                set_language("en_US")


if __name__ == "__main__":
    unittest.main()
