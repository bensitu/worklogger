"""Analytics summaries and charts."""

from __future__ import annotations

from dataclasses import replace
from copy import copy
from datetime import date
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QPushButton,
)

from worklogger.domain.shared.errors import AppError
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.presentation.job_runner import owned_callback
from worklogger.domain.shared.dates import add_months
from worklogger.domain.analytics.models import AnalyticsDashboard, ChartDataBundle
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_code, display_error_message
from worklogger.presentation.date_labels import month_label, month_name, duration_label
from worklogger.presentation.work_type_labels import work_type_label
from worklogger.presentation.viewmodels import (
    AnalyticsState,
    AnalyticsViewModel,
)
from worklogger.presentation.widgets import (
    CardFrame,
    ComboChart,
    DonutProgressCard,
    DotProgressCard,
    ExportMenuButton,
    OvertimeComparisonChart,
    SegmentedControl,
)
from worklogger.presentation.widgets.summary_card import SummaryCard
from worklogger.presentation.widgets.combo_chart import DonutChart
from worklogger.presentation.widgets.icons import set_button_icon
from PySide6.QtCore import Signal


class AnalyticsPage(QWidget):
    projects_requested = Signal()
    def __init__(
        self,
        view_model: AnalyticsViewModel | None,
        selected_day: date,
        parent: QWidget | None = None,
        *, job_runner=None, today=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("analytics_page_widget")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._view_model = view_model
        self._selected_day = selected_day
        self._state: AnalyticsState | None = None
        self._dashboard: AnalyticsDashboard | None = None
        self._last_error: AppError | None = None
        self._job_runner = job_runner
        self._today = today or date.today()
        self._load_revision = 0
        self._loading = False
        self._exporting = False
        self._build_ui()

    @property
    def last_error(self) -> AppError | None:
        return self._last_error

    def refresh(self, selected_day: date | None = None) -> bool:
        if selected_day is not None:
            self._selected_day = selected_day
            self._populate_periods()
        if self._view_model is None:
            self._set_status(_("Analytics is not configured."), error=True)
            return False
        scope = self.scope_control.value or "monthly"
        self._load_revision += 1
        revision, day = self._load_revision, self._selected_day
        if self._job_runner is not None:
            self._loading = True
            self.export_button.setEnabled(False)
            model = copy(self._view_model)
            def complete(result):
                if revision != self._load_revision:
                    return
                self._loading = False
                self.export_button.setEnabled(not self._exporting and result.ok)
                self._apply_dashboard(result, day, scope)
            try:
                self._job_runner.submit("load_analytics", lambda _token: model.load_dashboard(
                    year=day.year, month=day.month, scope=scope), on_complete=owned_callback(self, complete))
            except Exception:
                complete(Result.failure(InfrastructureError("analytics_load_failed", "analytics_load_failed")))
                return False
            return True
        result = self._view_model.load_dashboard(
            year=self._selected_day.year,
            month=self._selected_day.month,
            scope=scope,
        )
        return self._apply_dashboard(result, day, scope)

    def _apply_dashboard(self, result, day, scope):
        if not result.ok or result.value is None:
            self._last_error = result.error
            self._set_status(display_error_message(result.error), error=True)
            return False
        self._dashboard = result.value
        self._last_error = None
        self._state = AnalyticsState(self._view_model.user_id, day.year, day.month, scope, "hours", "bar", True, result.value.trend)
        self._set_state(result.value)
        self._set_status("")
        return True

    def export_csv(self, destination: Path) -> bool:
        if self._job_runner is not None:
            return self._export_async(destination, "csv")
        if self._view_model is None:
            return False
        if self._state is None and not self.refresh():
            return False
        assert self._state is not None
        result = self._view_model.export_csv(destination, self._state)
        if not result.ok or result.value is None:
            self._last_error = result.error
            self._set_status(display_error_message(result.error), error=True)
            return False
        self._set_status(_("Exported CSV"))
        return True

    def export_pdf(self, destination: Path) -> bool:
        if self._job_runner is not None:
            return self._export_async(destination, "pdf")
        if self._view_model is None:
            return False
        if self._state is None and not self.refresh():
            return False
        assert self._state is not None
        result = self._view_model.export_pdf(destination, self._state)
        if not result.ok or result.value is None:
            self._last_error = result.error
            self._set_status(display_error_message(result.error), error=True)
            return False
        self._set_status(_("Exported PDF"))
        return True

    def _export_async(self, destination, kind):
        if self._view_model is None or self._state is None or self._loading or self._exporting:
            return False
        state = self._state
        exporter = self._view_model.export_csv if kind == "csv" else self._view_model.export_pdf
        self._exporting = True
        self.export_button.setEnabled(False)
        def complete(result):
            self._exporting = False
            self.export_button.setEnabled(not self._loading and self._state is not None)
            if result.ok:
                self._set_status(_("Exported CSV") if kind == "csv" else _("Exported PDF"))
            else:
                self._last_error = result.error
                self._set_status(display_error_message(result.error), error=True)
        try:
            self._job_runner.submit("export_analytics", lambda _token: exporter(destination, state),
                                    on_complete=owned_callback(self, complete))
        except Exception:
            complete(Result.failure(InfrastructureError("analytics_export_failed", "analytics_export_failed")))
            return False
        return True

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        header = QHBoxLayout()
        self.scope_control = SegmentedControl(
            (
                ("monthly", _("Monthly")),
                ("quarterly", _("Quarterly")),
                ("annual", _("Annual")),
            )
        )
        self.scope_control.value_changed.connect(self._scope_changed)
        header.addWidget(self.scope_control)
        header.addStretch(1)
        self.period_combo = QComboBox()
        self.period_combo.setObjectName("analytics_period_combo")
        self.period_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.period_combo.currentIndexChanged.connect(self._period_changed)
        self._populate_periods()
        header.addWidget(self.period_combo)
        self.projects_button = QPushButton(_("Projects"))
        self.projects_button.setObjectName("analytics_projects_button")
        set_button_icon(self.projects_button, "folder-kanban")
        self.projects_button.clicked.connect(self.projects_requested)
        header.addWidget(self.projects_button)
        self.export_button = ExportMenuButton(
            _("Export"),
            (("csv", _("CSV")), ("pdf", _("PDF"))),
        )
        self.export_button.setObjectName("analytics_export_button")
        self.export_button.export_requested.connect(self._choose_export_path)
        header.addWidget(self.export_button)
        root.addLayout(header)

        scroll = QScrollArea()
        scroll.setObjectName("analytics_scroll_widget")
        scroll.setWidgetResizable(True)
        body = QWidget()
        body.setObjectName("analytics_content_widget")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(12)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)
        summary_grid = QGridLayout()
        summary_grid.setHorizontalSpacing(12)
        summary_grid.setVerticalSpacing(12)
        self.monthly_hours_card = DonutProgressCard(_("Monthly Hours"))
        self.overtime_chart = OvertimeComparisonChart()
        self.overtime_card = SummaryCard(_("Overtime Hours"), visual=self.overtime_chart,
                                         object_name="analytics_summary_card_frame")
        self.overtime_title_label = self.overtime_card.title_label
        self.overtime_value_label = self.overtime_card.value_label
        self.overtime_caption_label = self.overtime_card.caption_label
        self.attendance_card = DotProgressCard(_("Actual attendance"), color_role="success")
        self.attendance_card.setToolTip(_("Attendance counts dates with positive worked hours, including scheduled days off. Planned work follows the weekly schedule and enabled regional public holidays. This is not an attendance rate."))
        self.rest_card = DotProgressCard(_("Rest Days"), color_role="muted_text")
        self.rest_card.setToolTip(_("Dates with recorded break periods. Work and rest days may overlap; leave is counted separately."))
        summary_grid.addWidget(self.monthly_hours_card, 0, 0)
        summary_grid.addWidget(self.overtime_card, 0, 1)
        summary_grid.addWidget(self.attendance_card, 0, 2)
        summary_grid.addWidget(self.rest_card, 0, 3)
        for column in range(4):
            summary_grid.setColumnStretch(column, 1)
        body_layout.addLayout(summary_grid)

        charts = QGridLayout()
        charts.setHorizontalSpacing(12)
        charts.setVerticalSpacing(12)
        self.trend_chart = self._chart_card(_("Work Hours Trend"))
        self.average_chart = self._chart_card(_("Average Work Hours"))
        self.breakdown_chart = self._chart_card(_("Work Mode Breakdown"), donut=True)
        self.daily_average_chart = self._chart_card(_("Daily Average"))
        self.daily_average_value_label = QLabel("")
        self.daily_average_value_label.setObjectName("daily_average_value_label")
        self.daily_average_comparison_label = QLabel("")
        self.daily_average_comparison_label.setObjectName("daily_average_comparison_label")
        self.daily_average_comparison_label.setProperty("role", "secondary")
        self.daily_average_comparison_label.setWordWrap(True)
        average_row = QHBoxLayout()
        average_row.addWidget(self.daily_average_value_label)
        average_row.addWidget(self.daily_average_comparison_label, 1)
        self.daily_average_chart.content_layout.insertLayout(1, average_row)
        charts.addWidget(self.trend_chart, 0, 0)
        charts.addWidget(self.average_chart, 0, 1)
        charts.addWidget(self.breakdown_chart, 1, 0)
        charts.addWidget(self.daily_average_chart, 1, 1)
        body_layout.addLayout(charts, 1)
        self._summary_grid = summary_grid

        self.status_label = QLabel("")
        self.status_label.setObjectName("analytics_status_label")
        self.status_label.setProperty("role", "secondary")
        self.status_label.hide()
        root.addWidget(self.status_label)

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)
        if not hasattr(self, "_summary_grid"):
            return
        columns = 4 if self.width() >= 850 else 2
        cards = (self.monthly_hours_card, self.overtime_card, self.attendance_card, self.rest_card)
        for index, card in enumerate(cards):
            self._summary_grid.addWidget(card, index // columns, index % columns)
        for column in range(4):
            self._summary_grid.setColumnStretch(column, 1 if column < columns else 0)

    def _set_status(self, message: str, *, error: bool = False) -> None:
        self.status_label.setText(message)
        self.status_label.setVisible(bool(message))
        if message and error:
            QMessageBox.warning(self, _("Analytics"), message)

    def _chart_card(self, title: str, *, donut: bool = False) -> CardFrame:
        card = CardFrame(object_name="analytics_chart_frame")
        label = QLabel(title)
        label.setObjectName("analytics_chart_title_label")
        chart = DonutChart() if donut else ComboChart()
        card.chart = chart
        card.content_layout.addWidget(label)
        card.content_layout.addWidget(chart, 1)
        return card

    def _set_state(self, state: AnalyticsDashboard) -> None:
        total = state.stats.total_hours
        progress = total / state.target_hours if state.target_hours is not None and state.target_hours > 0 else 0.0
        titles = {
            "monthly": _("Monthly Hours"),
            "quarterly": _("Quarterly Hours"),
            "annual": _("Annual Hours"),
        }
        self.monthly_hours_card.title_label.setText(titles.get(self.scope_control.value, titles["monthly"]))
        self.monthly_hours_card.set_value(
            duration_label(total),
            _("Goal unavailable") if state.target_hours is None else _("of {hours:.1f}h goal").format(hours=state.target_hours),
            progress,
        )
        self.monthly_hours_card.gauge.setVisible(state.target_hours is not None)
        planning_error = display_error_code(state.planning_error) if state.planning_error else ""
        self.monthly_hours_card.setToolTip(planning_error if state.target_hours is None else
            _("Calculated from work schedule and holiday settings.") if state.target_mode == "schedule" else _("Custom monthly goal."))
        self.attendance_card.setToolTip(planning_error or _("Attendance counts dates with positive worked hours, including scheduled days off. Planned work follows the weekly schedule and enabled regional public holidays. This is not an attendance rate."))
        self.overtime_value_label.setText(duration_label(state.stats.overtime_hours))
        self.overtime_chart.set_hours(state.stats.overtime_hours, state.previous_stats.overtime_hours)
        self.overtime_caption_label.setText(_("{change:+.1f}h vs previous period").format(change=state.stats.overtime_hours - state.previous_stats.overtime_hours))
        days = state.stats.work_days
        rest = state.stats.rest_days
        self.attendance_card.set_value(_("{days} days").format(days=days),
            (_("Planned work unavailable") if state.planned_work_days is None else _("Planned work: {days:g} days").format(days=state.planned_work_days))
            + "\n" + _("{change:+d} days vs previous period").format(change=days - state.previous_stats.work_days),
            days, state.total_days)
        self.rest_card.set_value(str(rest), _("{change:+d} days vs previous period").format(change=rest - state.previous_stats.rest_days), rest, state.total_days)
        monthly = self.scope_control.value == "monthly"
        self.trend_chart.chart.set_data(state.trend if monthly else _month_chart_labels(state.trend), mode="bar")
        self.average_chart.chart.set_data(state.average if monthly else _month_chart_labels(state.average), mode="bar", average=True)
        mode_order = {"normal": 0, "remote": 1, "business_trip": 2, "meeting": 3, "training": 4, "leave": 5, "other": 6}
        work_modes = sorted(state.work_modes, key=lambda item: mode_order.get(item[0], 4))
        self.breakdown_chart.chart.set_segments(
            tuple((dict(state.work_mode_labels).get(key) or work_type_label(key) or key, value) for key, value in work_modes),
            keys=tuple(key for key, _value in work_modes),
        )
        self.daily_average_value_label.setText(duration_label(state.stats.average_hours))
        self.daily_average_comparison_label.setText(_("{change:+.1f}h vs previous period").format(change=state.stats.average_hours - state.previous_stats.average_hours))
        daily_labels = _quarter_chart_labels if self.scope_control.value == "quarterly" else _month_chart_labels
        self.daily_average_chart.chart.set_data(daily_labels(state.daily_average_trend), mode="line", average=True)

    def _populate_periods(self) -> None:
        scope = self.scope_control.value or "monthly"
        selected = self._selected_day.replace(day=1)
        latest = max(self._today.replace(day=1), selected)
        self.period_combo.blockSignals(True)
        self.period_combo.clear()
        if scope == "annual":
            values = [date(year, 1, 1) for year in range(min(9999, latest.year + 1), max(0, latest.year - 10), -1)]
        else:
            step = 3 if scope == "quarterly" else 1
            if step == 3:
                selected = selected.replace(month=((selected.month - 1) // 3) * 3 + 1)
                latest = latest.replace(month=((latest.month - 1) // 3) * 3 + 1)
            values = []
            for offset in range(1, -36, -1):
                try:
                    values.append(add_months(latest, offset * step))
                except ValueError:
                    continue
        target = selected.replace(month=1) if scope == "annual" else selected
        if target not in values:
            values.append(target)
            values.sort(reverse=True)
        for value in values:
            label = str(value.year) if scope == "annual" else (_("Q{quarter} {year}").format(quarter=(value.month - 1) // 3 + 1, year=value.year) if scope == "quarterly" else month_label(value))
            self.period_combo.addItem(label, value)
        self.period_combo.setCurrentIndex(values.index(target))
        self.period_combo.blockSignals(False)

    def _scope_changed(self, _scope: str) -> None:
        self._populate_periods()
        self.refresh()

    def _period_changed(self, index: int) -> None:
        value = self.period_combo.itemData(index)
        if isinstance(value, date):
            self._selected_day = value
            self.refresh()

    def _choose_export_path(self, kind: str) -> None:
        if kind == "csv":
            path, _selected = QFileDialog.getSaveFileName(
                self,
                _("Export CSV"),
                "analytics.csv",
                _("CSV files (*.csv)"),
            )
            if path:
                self.export_csv(Path(path))
            return
        path, _selected = QFileDialog.getSaveFileName(
            self,
            _("Export PDF"),
            "analytics.pdf",
            _("PDF files (*.pdf)"),
        )
        if path:
            self.export_pdf(Path(path))

def _month_chart_labels(bundle: ChartDataBundle) -> ChartDataBundle:
    def labels(values: tuple[tuple[str, float], ...]) -> tuple[tuple[str, float], ...]:
        return tuple((month_name(date(2000, int(label), 1)), value) for label, value in values)
    return replace(bundle, bar_data=labels(bundle.bar_data), line_data=labels(bundle.line_data), leave_hours_data=labels(bundle.leave_hours_data))

def _quarter_chart_labels(bundle: ChartDataBundle) -> ChartDataBundle:
    def labels(values: tuple[tuple[str, float], ...]) -> tuple[tuple[str, float], ...]:
        return tuple((_("Q{quarter}").format(quarter=int(label[1:])), value) for label, value in values)
    return replace(bundle, bar_data=labels(bundle.bar_data), line_data=labels(bundle.line_data), leave_hours_data=labels(bundle.leave_hours_data))
