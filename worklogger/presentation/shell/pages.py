"""In-window shell pages for the primary product areas."""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Callable
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QComboBox,
    QGridLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from worklogger.domain.shared.errors import AppError, CancellationError, ValidationError
from worklogger.domain.shared.dates import add_months
from worklogger.domain.analytics.models import AnalyticsDashboard, ChartDataBundle
from worklogger.app.job_runner import JobRunner
from worklogger.presentation.job_runner import QtJobRunner
from worklogger.presentation.reporting.dialog import ReportTemplateDialog, confirm_report_overwrite
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.date_labels import month_label, month_name, period_range_label, duration_label
from worklogger.presentation.work_type_labels import work_type_label
from worklogger.presentation.viewmodels import (
    AnalyticsState,
    AnalyticsViewModel,
    ReportEditorState,
    ReportEditorViewModel,
)
from worklogger.presentation.widgets import (
    CalendarView,
    CardFrame,
    ComboChart,
    DonutProgressCard,
    DotProgressCard,
    ExportMenuButton,
    OvertimeComparisonChart,
    ReportHistoryDisplayItem,
    ReportHistoryPanel,
    SegmentedControl,
    StatsPanel,
    SummaryValueLabel,
    WorkLogEntryPanel,
)
from worklogger.presentation.widgets.combo_chart import DonutChart
from worklogger.presentation.widgets.icons import IconLabel, set_button_icon
from worklogger.presentation.widgets.record_summary import RecordSummaryLabel


class CalendarPage(QWidget):
    previous_month_requested = Signal()
    next_month_requested = Signal()
    today_requested = Signal()

    def __init__(
        self,
        *,
        calendar_view: CalendarView,
        entry_panel: WorkLogEntryPanel,
        stats_panel: StatsPanel,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("calendar_page_widget")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.calendar_view = calendar_view
        self.entry_panel = entry_panel
        self.stats_panel = stats_panel
        self._build_ui()

    def set_month_title(self, title: str) -> None:
        self.month_title_label.setText(title)
        QTimer.singleShot(0, self, self._ensure_selected_day_visible)

    def _ensure_selected_day_visible(self) -> None:
        selected = next((button for button in self.calendar_view.day_buttons()
                         if button.cell is not None and button.cell.is_selected and button.cell.in_month), None)
        if selected is not None:
            self.calendar_scroll.ensureWidgetVisible(selected, 0, 8)

    def set_record_summary(self, lines: tuple[str, ...]) -> None:
        while self.records_layout.count():
            item = self.records_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        if not lines:
            empty = QLabel(_("No records for the selected day."))
            empty.setObjectName("calendar_empty_records_label")
            empty.setProperty("role", "secondary")
            empty.setWordWrap(True)
            self.records_layout.addWidget(empty)
            self.records_layout.addStretch(1)
            return
        for line in lines:
            record = QFrame()
            record.setObjectName("calendar_record_frame")
            row = QHBoxLayout(record)
            row.setContentsMargins(8, 8, 8, 8)
            row.setSpacing(6)
            row.addWidget(RecordSummaryLabel(line), 1)
            self.records_layout.addWidget(record)
        self.records_layout.addStretch(1)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        header = QHBoxLayout()
        self.header_layout = header
        header.setContentsMargins(0, 0, 0, 0)
        self.previous_month_button = QPushButton("<")
        self.previous_month_button.setObjectName("previous_month_button")
        self.previous_month_button.setProperty("variant", "ghost")
        self.previous_month_button.setToolTip(_("Previous month"))
        set_button_icon(self.previous_month_button, "chevron-left")
        self.previous_month_button.setText("")
        self.previous_month_button.clicked.connect(self.previous_month_requested.emit)
        self.month_title_label = QLabel("")
        self.month_title_label.setObjectName("calendar_month_title_label")
        self.month_title_label.setProperty("role", "title")
        self.month_title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.next_month_button = QPushButton(">")
        self.next_month_button.setObjectName("next_month_button")
        self.next_month_button.setProperty("variant", "ghost")
        self.next_month_button.setToolTip(_("Next month"))
        set_button_icon(self.next_month_button, "chevron-right")
        self.next_month_button.setText("")
        self.next_month_button.clicked.connect(self.next_month_requested.emit)
        self.today_button = QPushButton(_("Today"))
        self.today_button.setObjectName("today_button")
        self.today_button.clicked.connect(self.today_requested.emit)
        self.add_entry_button = QPushButton(_("+ Add Entry"))
        self.add_entry_button.setObjectName("add_entry_button")
        self.add_entry_button.setProperty("variant", "primary")
        self.add_entry_button.setText(_("Add Entry"))
        set_button_icon(self.add_entry_button, "plus")
        self.add_entry_button.setToolTip(_("More actions"))
        header.addWidget(self.previous_month_button)
        header.addStretch(1)
        header.addWidget(self.month_title_label)
        header.addStretch(1)
        header.addWidget(self.next_month_button)
        header.addWidget(self.today_button)
        header.addWidget(self.add_entry_button)
        root.addLayout(header)

        content = QHBoxLayout()
        content.setSpacing(16)
        root.addLayout(content, 1)

        self.calendar_view.month_title.setVisible(False)
        self.calendar_view.set_month_only(True)
        self.calendar_scroll = QScrollArea()
        self.calendar_scroll.setObjectName("calendar_scroll_widget")
        self.calendar_scroll.viewport().setObjectName("calendar_scroll_viewport_widget")
        self.calendar_scroll.setWidgetResizable(True)
        self.calendar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.calendar_scroll.setWidget(self.calendar_view)
        content.addWidget(self.calendar_scroll, 1)

        self.details_scroll = QScrollArea()
        self.details_scroll.setObjectName("calendar_details_scroll_widget")
        self.details_scroll.setWidgetResizable(True)
        self.details_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.details_scroll.setFixedWidth(236)
        right = QFrame()
        right.setObjectName("calendar_right_panel_frame")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 0, 0, 0)
        right_layout.setSpacing(10)
        self.details_scroll.setWidget(right)
        self.stats_panel.setVisible(False)
        right_layout.addWidget(self.entry_panel)
        right_layout.addWidget(self.stats_panel)
        separator = QLabel(_("Schedule / Records"))
        separator.setObjectName("schedule_records_label")
        right_layout.addWidget(separator)
        self.records_scroll = QScrollArea()
        self.records_scroll.setObjectName("calendar_records_scroll_widget")
        self.records_scroll.setWidgetResizable(True)
        self.records_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.records_scroll.setMinimumHeight(96)
        self.records_widget = QWidget()
        self.records_widget.setObjectName("calendar_records_widget")
        self.records_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.records_layout = QVBoxLayout(self.records_widget)
        self.records_layout.setContentsMargins(0, 0, 0, 0)
        self.records_layout.setSpacing(4)
        self.records_scroll.setWidget(self.records_widget)
        right_layout.addWidget(self.records_scroll, 1)
        content.addWidget(self.details_scroll)


class AnalyticsPage(QWidget):
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
        self.export_button = ExportMenuButton(
            _("Export"),
            (("csv", _("CSV")), ("pdf", _("PDF"))),
        )
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
        self.rest_card = DotProgressCard(_("Rest Days"), color="#ef4444")
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
        rest = state.total_days - days
        self.attendance_card.set_value(f"{days} / {state.total_days}", _("{change:+d} days vs previous period").format(change=days - state.previous_stats.work_days), days, state.total_days)
        self.rest_card.set_value(str(rest), _("{change:+d} days vs previous period").format(change=rest - (state.previous_total_days - state.previous_stats.work_days)), rest, state.total_days)
        monthly = self.scope_control.value == "monthly"
        self.trend_chart.chart.set_data(state.trend if monthly else _month_chart_labels(state.trend), mode="bar")
        self.average_chart.chart.set_data(state.average if monthly else _month_chart_labels(state.average), mode="bar", average=True)
        mode_order = {"normal": 0, "remote": 1, "business_trip": 2, "leave": 3}
        work_modes = sorted(state.work_modes, key=lambda item: mode_order.get(item[0], 4))
        self.breakdown_chart.chart.set_segments(
            tuple((work_type_label(key) or key, value) for key, value in work_modes),
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


class ReportsPage(QWidget):
    def __init__(
        self,
        view_model: ReportEditorViewModel | None,
        selected_day: date,
        parent: QWidget | None = None,
        *,
        confirm_discard: Callable[[], bool] | None = None,
        job_runner: JobRunner | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("reports_page_widget")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._view_model = view_model
        self._selected_day = selected_day
        self._states: dict[str, ReportEditorState] = {}
        self._saved_content: dict[str, str] = {}
        self._last_error: AppError | None = None
        self._rendered_type = "daily"
        self._confirm_discard = confirm_discard
        self._job_runner = job_runner or QtJobRunner(self)
        self._rewrite_busy = False
        self._build_ui()

    @property
    def last_error(self) -> AppError | None:
        return self._last_error

    @property
    def has_unsaved_changes(self) -> bool:
        return self.editor.toPlainText() != self._saved_content.get(self._rendered_type, "")

    def confirm_leave(self) -> bool:
        if self._rewrite_busy:
            self._set_status(_("Please wait for the current request."))
            return False
        if not self.has_unsaved_changes:
            return True
        confirmed = (
            self._confirm_discard()
            if self._confirm_discard is not None
            else QMessageBox.question(
                self,
                _("Discard changes?"),
                _("You have unsaved report changes. Discard them?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            ) == QMessageBox.StandardButton.Yes
        )
        if confirmed:
            self.editor.setPlainText(self._saved_content.get(self._rendered_type, ""))
        return bool(confirmed)

    def refresh(self, selected_day: date | None = None) -> bool:
        if not self.confirm_leave():
            return False
        if selected_day is not None:
            self._selected_day = selected_day
        if self._view_model is None:
            self._set_status(_("Reports are not configured."), error=True)
            return False
        ok = True
        for report_type in ("daily", "weekly", "monthly"):
            result = self._view_model.load(report_type, self._selected_day)
            if not result.ok or result.value is None:
                self._set_error(result.error)
                ok = False
                continue
            self._states[report_type] = result.value
            self._saved_content[report_type] = result.value.content
        self._render_current()
        self._refresh_history()
        if ok:
            self._set_status("")
        return ok

    def copy_markdown(self) -> None:
        QApplication.clipboard().setText(self.editor.toPlainText())
        self._set_status(_("Copied"))

    def export_markdown(self, destination: Path) -> bool:
        if self._view_model is None:
            return False
        result = self._view_model.export_markdown(destination, self.editor.toPlainText())
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return False
        self._set_status(_("Exported Markdown"))
        return True

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        self.report_type_control = SegmentedControl(
            (
                ("daily", _("Daily Report")),
                ("weekly", _("Weekly Report")),
                ("monthly", _("Monthly Report")),
            ), tabs=True,
        )
        self.report_type_control.value_changed.connect(self._change_report_type)
        root.addWidget(self.report_type_control)

        content = QHBoxLayout()
        content.setSpacing(16)
        root.addLayout(content, 1)

        editor_card = CardFrame(object_name="report_editor_frame")
        period_row = QHBoxLayout()
        self.period_title_label = QLabel("")
        self.period_title_label.setObjectName("report_period_label")
        self.period_title_label.setProperty("role", "title")
        self.previous_period_button = QPushButton("<")
        self.previous_period_button.setObjectName("previous_report_period_button")
        self.previous_period_button.setProperty("variant", "outline")
        self.previous_period_button.clicked.connect(lambda: self._shift_period(-1))
        self.previous_period_button.setToolTip(_("Previous period"))
        set_button_icon(self.previous_period_button, "chevron-left")
        self.previous_period_button.setText("")
        self.next_period_button = QPushButton(">")
        self.next_period_button.setObjectName("next_report_period_button")
        self.next_period_button.setProperty("variant", "outline")
        self.next_period_button.clicked.connect(lambda: self._shift_period(1))
        self.next_period_button.setToolTip(_("Next period"))
        set_button_icon(self.next_period_button, "chevron-right")
        self.next_period_button.setText("")
        period_row.addWidget(IconLabel("calendar-days"))
        self.period_title_label.setWordWrap(True)
        period_row.addWidget(self.period_title_label, 1)
        self.previous_period_button.setFixedWidth(34)
        self.next_period_button.setFixedWidth(34)
        period_row.addWidget(self.previous_period_button)
        period_row.addWidget(self.next_period_button)
        editor_card.content_layout.addLayout(period_row)
        divider = QFrame()
        divider.setObjectName("report_period_separator_frame")
        divider.setFixedHeight(1)
        editor_card.content_layout.addWidget(divider)

        report_row = QHBoxLayout()
        report_title = QLabel(_("Report"))
        report_title.setObjectName("report_title_label")
        self.templates_button = QPushButton(_("Templates"))
        self.templates_button.setObjectName("templates_button")
        self.templates_button.setProperty("variant", "outline")
        self.templates_button.clicked.connect(self._open_templates)
        set_button_icon(self.templates_button, "file-text", accent=True)
        report_row.addWidget(report_title, 1)
        report_row.addWidget(self.templates_button)
        editor_card.content_layout.addLayout(report_row)

        self.editor = QTextEdit()
        self.editor.setObjectName("report_text_edit")
        editor_card.content_layout.addWidget(self.editor, 1)

        self.ai_hint_line_edit = QLineEdit()
        self.ai_hint_line_edit.setObjectName("ai_hint_line_edit")
        self.ai_hint_line_edit.setPlaceholderText(_("AI Assist Hint / extra instructions (optional)"))
        editor_card.content_layout.addWidget(self.ai_hint_line_edit)

        ai_row = QHBoxLayout()
        self.ai_assist_button = QPushButton(_("AI Assist"))
        self.ai_assist_button.setObjectName("report_ai_assist_button")
        self.ai_assist_button.setProperty("variant", "outline")
        self.ai_assist_button.clicked.connect(self._rewrite_current)
        set_button_icon(self.ai_assist_button, "sparkles", accent=True)
        if self._view_model is None or not getattr(self._view_model, "rewrite_available", True):
            self.ai_assist_button.setEnabled(False)
            self.ai_assist_button.setToolTip(_("AI Assist is not configured."))
        self.tip_label = QLabel(_("Tip: Click AI Assist to generate a draft based on your time logs."))
        self.tip_label.setObjectName("report_tip_label")
        self.tip_label.setProperty("role", "secondary")
        self.tip_label.setWordWrap(True)
        ai_row.addWidget(self.ai_assist_button)
        ai_row.addWidget(self.tip_label, 1)
        editor_card.content_layout.addLayout(ai_row)

        bottom = QHBoxLayout()
        self.copy_button = QPushButton(_("Copy"))
        self.copy_button.setObjectName("copy_report_button")
        self.copy_button.clicked.connect(self.copy_markdown)
        set_button_icon(self.copy_button, "copy")
        self.save_button = QPushButton(_("Save Report"))
        self.save_button.setObjectName("save_report_button")
        self.save_button.setProperty("variant", "primary")
        self.save_button.clicked.connect(self._save_current)
        set_button_icon(self.save_button, "save")
        bottom.addWidget(self.copy_button)
        bottom.addStretch(1)
        bottom.addWidget(self.save_button)
        editor_card.content_layout.addLayout(bottom)
        content.addWidget(editor_card, 2)

        self.history_panel = ReportHistoryPanel()
        self.history_panel.item_selected.connect(self._select_history_item)
        self.history_panel.export_requested.connect(self._choose_export_path)
        content.addWidget(self.history_panel, 1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("reports_status_label")
        self.status_label.setProperty("role", "secondary")
        self.status_label.hide()
        root.addWidget(self.status_label)

    def _set_status(self, message: str, *, notify: bool = True, error: bool = False) -> None:
        self.status_label.setText(message)
        self.status_label.hide()
        if message and notify:
            show = QMessageBox.warning if error else QMessageBox.information
            show(self, _("Reports"), message)

    def _current_type(self) -> str:
        return self.report_type_control.value or "daily"

    def _change_report_type(self, report_type: str) -> None:
        if not self.confirm_leave():
            self.report_type_control.set_value(self._rendered_type, emit=False)
            return
        self._render_current()

    def _shift_period(self, direction: int) -> None:
        state = self._states.get(self._current_type())
        day = state.period_start if state is not None else self._selected_day
        self.refresh(shift_period(day, self._current_type(), direction))

    def _open_templates(self) -> None:
        if self._view_model is None or self._rewrite_busy:
            return
        dialog = ReportTemplateDialog(self._view_model, self._current_type(), self)
        dialog.apply_requested.connect(self._apply_template)
        if dialog.refresh():
            dialog.exec()
        else:
            self._set_status(dialog.status_label.text(), error=True)

    def _apply_template(self) -> None:
        if self._view_model is None or not self.confirm_leave():
            return
        state = self._states.get(self._current_type())
        if state is None:
            return
        result = self._view_model.generate_draft(state)
        if result.ok and result.value is not None:
            self.editor.setPlainText(result.value)
        else:
            self._set_error(result.error)

    def _render_current(self) -> None:
        report_type = self._current_type()
        state = self._states.get(report_type)
        if state is None:
            return
        self._rendered_type = report_type
        self.period_title_label.setText(_period_label(state))
        self.editor.setPlainText(state.content)
        self._refresh_history()

    def _save_current(self) -> None:
        if self._view_model is None:
            return
        report_type = self._current_type()
        state = self._states.get(report_type)
        if state is None:
            self._set_error(ValidationError("report_not_loaded", "report_not_loaded"))
            return
        content = self.editor.toPlainText()
        if state.report_id is not None:
            if content == state.content or not confirm_report_overwrite(self):
                return
        result = self._view_model.save(state, content)
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return
        self._states[report_type] = result.value
        self._saved_content[report_type] = result.value.content
        self._set_status(_("Report saved."))
        self._refresh_history()

    def _rewrite_current(self) -> None:
        if self._view_model is None or self._rewrite_busy:
            return
        state = self._states.get(self._current_type())
        if state is None:
            self._set_error(ValidationError("report_not_loaded", "report_not_loaded"))
            return
        content = self.editor.toPlainText()
        instructions = self.ai_hint_line_edit.text()
        self._set_rewrite_busy(True)
        self._set_status(_("Rewriting report..."), notify=False)
        self._job_runner.submit(
            "rewrite_report", lambda _token: self._view_model.rewrite(state, content, instructions),
            on_complete=self._complete_rewrite,
        )

    def _set_rewrite_busy(self, busy: bool) -> None:
        self._rewrite_busy = busy
        self.editor.setReadOnly(busy)
        for widget in (self.report_type_control, self.previous_period_button, self.next_period_button, self.templates_button, self.ai_hint_line_edit, self.save_button, self.history_panel):
            widget.setEnabled(not busy)
        self.ai_assist_button.setEnabled(not busy and bool(getattr(self._view_model, "rewrite_available", True)))

    def _complete_rewrite(self, result: object) -> None:
        self._set_rewrite_busy(False)
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return
        self.editor.setPlainText(result.value)
        self._set_status(_("Rewritten"))

    def _refresh_history(self) -> None:
        if self._view_model is None:
            self.history_panel.set_items(())
            return
        result = self._view_model.list_history(self._current_type())
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return
        self.history_panel.set_items(
            ReportHistoryDisplayItem(
                report_id=item.report_id,
                user_id=item.user_id,
                report_type=item.report_type,
                period_start=item.period_start,
                period_end=item.period_end,
                label=period_range_label(item.period_start, item.period_end),
                content=item.content,
                saved=item.saved,
                created_at=item.created_at,
            )
            for item in result.value
        )
        state = self._states.get(self._current_type())
        self.history_panel.set_selected_report(state.report_id if state is not None else None)

    def _select_history_item(self, item: ReportHistoryDisplayItem) -> None:
        if not self._view_model or not self.confirm_leave():
            return
        state = ReportEditorState(
            user_id=item.user_id,
            report_type=item.report_type,
            period_start=item.period_start,
            period_end=item.period_end,
            content=item.content,
            saved=True,
            report_id=item.report_id,
            created_at=item.created_at,
        )
        self._states[item.report_type] = state
        self._saved_content[item.report_type] = state.content
        self._rendered_type = item.report_type
        self._selected_day = item.period_start
        self.report_type_control.set_value(item.report_type, emit=False)
        self.history_panel.set_selected_report(item.report_id)
        self.editor.setPlainText(state.content)
        self.period_title_label.setText(_period_label(state))

    def _choose_export_path(self) -> None:
        state = self._states.get(self._current_type())
        suffix = state.period_start.isoformat() if state is not None else self._selected_day.isoformat()
        path, _selected = QFileDialog.getSaveFileName(
            self,
            _("Export Markdown"),
            f"{self._current_type()}-report-{suffix}.md",
            _("Markdown files (*.md)"),
        )
        if path:
            self.export_markdown(Path(path))

    def _set_error(self, error: AppError | None) -> None:
        if isinstance(error, CancellationError):
            self._last_error = None
            self._set_status(display_error_message(error), notify=False)
            return
        self._last_error = error
        self._set_status(display_error_message(error), error=True)


class UnavailableSettingsPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settings_unavailable_page_widget")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        message = QLabel(_("Settings are not configured."))
        message.setObjectName("settings_unavailable_label")
        message.setProperty("role", "secondary")
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(message, 1)

    def refresh(self) -> bool:
        return False


def _period_label(state: ReportEditorState) -> str:
    label = period_range_label(state.period_start, state.period_end)
    if state.report_type == "weekly":
        label += " " + _("(Week {week})").format(week=state.period_start.isocalendar().week)
    return label


def _month_chart_labels(bundle: ChartDataBundle) -> ChartDataBundle:
    def labels(values: tuple[tuple[str, float], ...]) -> tuple[tuple[str, float], ...]:
        return tuple((month_name(date(2000, int(label), 1)), value) for label, value in values)
    return replace(bundle, bar_data=labels(bundle.bar_data), line_data=labels(bundle.line_data), leave_hours_data=labels(bundle.leave_hours_data))


def _quarter_chart_labels(bundle: ChartDataBundle) -> ChartDataBundle:
    def labels(values: tuple[tuple[str, float], ...]) -> tuple[tuple[str, float], ...]:
        return tuple((_("Q{quarter}").format(quarter=int(label[1:])), value) for label, value in values)
    return replace(bundle, bar_data=labels(bundle.bar_data), line_data=labels(bundle.line_data), leave_hours_data=labels(bundle.leave_hours_data))


def shift_period(day: date, report_type: str, direction: int) -> date:
    if report_type == "daily":
        return day + timedelta(days=direction)
    if report_type == "weekly":
        return day + timedelta(days=direction * 7)
    shifted = add_months(day.replace(day=1), direction)
    last = monthrange(shifted.year, shifted.month)[1]
    return shifted.replace(day=min(day.day, last))
