"""Analytics summaries and charts."""

from __future__ import annotations

from dataclasses import replace
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
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QPushButton,
)

from worklogger.domain.shared.errors import AppError
from worklogger.domain.shared.dates import add_months
from worklogger.domain.analytics.models import AnalyticsDashboard, ChartDataBundle
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_message
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
    SummaryValueLabel,
)
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
    ) -> None:
        super().__init__(parent)
        self.setObjectName("analytics_page_widget")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._view_model = view_model
        self._selected_day = selected_day
        self._state: AnalyticsState | None = None
        self._dashboard: AnalyticsDashboard | None = None
        self._last_error: AppError | None = None
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
        result = self._view_model.load_dashboard(
            year=self._selected_day.year,
            month=self._selected_day.month,
            scope=scope,
        )
        if not result.ok or result.value is None:
            self._last_error = result.error
            self._set_status(display_error_message(result.error), error=True)
            return False
        self._dashboard = result.value
        self._state = AnalyticsState(self._view_model.user_id, self._selected_day.year, self._selected_day.month, scope, "hours", "bar", True, result.value.trend)
        self._set_state(result.value)
        self._set_status("")
        return True

    def export_csv(self, destination: Path) -> bool:
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
        self.overtime_card = CardFrame(object_name="analytics_summary_card_frame")
        self.overtime_card.content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.overtime_title_label = QLabel(_("Overtime Hours"))
        self.overtime_title_label.setObjectName("overtime_title_label")
        self.overtime_title_label.setWordWrap(True)
        self.overtime_title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.overtime_title_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.overtime_value_label = SummaryValueLabel()
        self.overtime_value_label.setObjectName("overtime_value_label")
        self.overtime_caption_label = QLabel("")
        self.overtime_caption_label.setObjectName("overtime_caption_label")
        self.overtime_caption_label.setProperty("role", "secondary")
        self.overtime_caption_label.setWordWrap(True)
        self.overtime_chart = OvertimeComparisonChart()
        self.overtime_card.content_layout.addWidget(self.overtime_title_label)
        overtime_row = QHBoxLayout()
        overtime_row.setContentsMargins(0, 0, 0, 0)
        overtime_row.setSpacing(8)
        overtime_text = QVBoxLayout()
        overtime_text.setContentsMargins(0, 0, 0, 0)
        overtime_text.setSpacing(12)
        overtime_text.setAlignment(Qt.AlignmentFlag.AlignTop)
        overtime_text.addWidget(self.overtime_value_label)
        overtime_text.addWidget(self.overtime_caption_label)
        overtime_row.addLayout(overtime_text, 1)
        overtime_row.addWidget(self.overtime_chart)
        self.overtime_card.content_layout.addLayout(overtime_row)
        self.attendance_card = DotProgressCard(_("Attendance Days"), color="#16a34a")
        self.rest_card = DotProgressCard(_("Rest Days"), color="#64748b")
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
        self.status_label.hide()
        if message:
            show = QMessageBox.warning if error else QMessageBox.information
            show(self, _("Analytics"), message)

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
        progress = total / state.target_hours if state.target_hours > 0 else 0.0
        titles = {
            "monthly": _("Monthly Hours"),
            "quarterly": _("Quarterly Hours"),
            "annual": _("Annual Hours"),
        }
        self.monthly_hours_card.title_label.setText(titles.get(self.scope_control.value, titles["monthly"]))
        self.monthly_hours_card.set_value(
            duration_label(total),
            _("of {hours:.1f}h goal").format(hours=state.target_hours),
            progress,
        )
        self.overtime_value_label.setText(duration_label(state.stats.overtime_hours))
        self.overtime_chart.set_hours(state.stats.overtime_hours, state.previous_stats.overtime_hours)
        self.overtime_caption_label.setText(_("{change:+.1f}h vs previous period").format(change=state.stats.overtime_hours - state.previous_stats.overtime_hours))
        days = state.stats.work_days
        rest = state.stats.rest_days
        self.attendance_card.set_value(f"{days} / {state.total_days}", _("{change:+d} days vs previous period").format(change=days - state.previous_stats.work_days), days, state.total_days)
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
        latest = max(date.today().replace(day=1), selected)
        self.period_combo.blockSignals(True)
        self.period_combo.clear()
        if scope == "annual":
            values = [date(year, 1, 1) for year in range(latest.year + 1, latest.year - 10, -1)]
        else:
            step = 3 if scope == "quarterly" else 1
            if step == 3:
                selected = selected.replace(month=((selected.month - 1) // 3) * 3 + 1)
                latest = latest.replace(month=((latest.month - 1) // 3) * 3 + 1)
            values = [add_months(latest, offset * step) for offset in range(1, -36, -1)]
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
