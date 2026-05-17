"""In-window shell pages for the primary product areas."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from worklogger.domain.shared.errors import AppError, ValidationError
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_message
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
    PageHeader,
    ReportHistoryDisplayItem,
    ReportHistoryPanel,
    SegmentedControl,
    StatsPanel,
    WorkLogEntryPanel,
)


class SettingsWorkflowWithDialog(Protocol):
    def create_dialog(self, parent: QWidget | None = None) -> QWidget:
        ...


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
        self.calendar_view = calendar_view
        self.entry_panel = entry_panel
        self.stats_panel = stats_panel
        self._build_ui()
        self.entry_panel.time_tabs.tabBar().setVisible(False)

    def set_month_title(self, title: str) -> None:
        self.month_title_label.setText(title)

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
            label = QLabel(line)
            label.setObjectName("calendar_record_label")
            label.setWordWrap(True)
            self.records_layout.addWidget(label)
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
        self.previous_month_button.clicked.connect(self.previous_month_requested.emit)
        self.month_title_label = QLabel("")
        self.month_title_label.setObjectName("calendar_month_title_label")
        self.month_title_label.setProperty("role", "title")
        self.month_title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.next_month_button = QPushButton(">")
        self.next_month_button.setObjectName("next_month_button")
        self.next_month_button.setProperty("variant", "ghost")
        self.next_month_button.setToolTip(_("Next month"))
        self.next_month_button.clicked.connect(self.next_month_requested.emit)
        self.today_button = QPushButton(_("Today"))
        self.today_button.setObjectName("today_button")
        self.today_button.clicked.connect(self.today_requested.emit)
        self.add_entry_button = QPushButton(_("+ Add Entry"))
        self.add_entry_button.setObjectName("add_entry_button")
        self.add_entry_button.setProperty("variant", "primary")
        self.add_entry_button.clicked.connect(self.entry_panel.setFocus)
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
        content.addWidget(self.calendar_view, 1)

        right = CardFrame(object_name="calendar_right_panel_frame")
        right.setFixedWidth(260)
        self.stats_panel.setVisible(False)
        right.content_layout.addWidget(self.entry_panel)
        right.content_layout.addWidget(self.stats_panel)
        separator = QLabel(_("Schedule / Records"))
        separator.setObjectName("schedule_records_label")
        right.content_layout.addWidget(separator)
        self.records_widget = QWidget()
        self.records_widget.setObjectName("calendar_records_widget")
        self.records_layout = QVBoxLayout(self.records_widget)
        self.records_layout.setContentsMargins(0, 0, 0, 0)
        self.records_layout.setSpacing(8)
        right.content_layout.addWidget(self.records_widget, 1)
        content.addWidget(right)


class AnalyticsPage(QWidget):
    def __init__(
        self,
        view_model: AnalyticsViewModel | None,
        selected_day: date,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("analytics_page_widget")
        self._view_model = view_model
        self._selected_day = selected_day
        self._state: AnalyticsState | None = None
        self._last_error: AppError | None = None
        self._build_ui()

    @property
    def last_error(self) -> AppError | None:
        return self._last_error

    def refresh(self, selected_day: date | None = None) -> bool:
        if selected_day is not None:
            self._selected_day = selected_day
        if self._view_model is None:
            self.status_label.setText(_("Analytics is not configured."))
            return False
        result = self._view_model.load(
            year=self._selected_day.year,
            month=self._selected_day.month,
            scope=self.scope_control.value or "monthly",
            metric="hours",
            chart_mode="bar",
            include_leaves=True,
        )
        if not result.ok or result.value is None:
            self._last_error = result.error
            self.status_label.setText(display_error_message(result.error))
            return False
        self._state = result.value
        self._set_state(result.value)
        self.status_label.setText(_("Ready"))
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
            self.status_label.setText(display_error_message(result.error))
            return False
        self.status_label.setText(_("Exported CSV"))
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
            self.status_label.setText(display_error_message(result.error))
            return False
        self.status_label.setText(_("Exported PDF"))
        return True

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        header = PageHeader(_("Analytics"))
        self.scope_control = SegmentedControl(
            (
                ("monthly", _("Monthly")),
                ("quarterly", _("Quarterly")),
                ("annual", _("Annual")),
            )
        )
        self.scope_control.value_changed.connect(lambda _value: self.refresh())
        header.actions_layout.addWidget(self.scope_control)
        self.period_combo = QComboBox()
        self.period_combo.setObjectName("analytics_period_combo")
        self.period_combo.addItem(self._selected_day.strftime("%B %Y"))
        header.actions_layout.addWidget(self.period_combo)
        self.export_button = ExportMenuButton(
            _("Export"),
            (("csv", _("CSV")), ("pdf", _("PDF"))),
        )
        self.export_button.export_requested.connect(self._choose_export_path)
        header.actions_layout.addWidget(self.export_button)
        root.addWidget(header)

        summary_grid = QGridLayout()
        summary_grid.setHorizontalSpacing(12)
        summary_grid.setVerticalSpacing(12)
        self.monthly_hours_card = DonutProgressCard(_("Monthly Hours"))
        self.overtime_card = CardFrame(object_name="analytics_summary_card_frame")
        self.overtime_title_label = QLabel(_("Overtime Hours"))
        self.overtime_title_label.setObjectName("overtime_title_label")
        self.overtime_value_label = QLabel("")
        self.overtime_value_label.setObjectName("overtime_value_label")
        self.overtime_caption_label = QLabel("")
        self.overtime_caption_label.setObjectName("overtime_caption_label")
        self.overtime_caption_label.setProperty("role", "secondary")
        self.overtime_card.content_layout.addWidget(self.overtime_title_label)
        self.overtime_card.content_layout.addWidget(self.overtime_value_label)
        self.overtime_card.content_layout.addWidget(self.overtime_caption_label)
        self.attendance_card = DotProgressCard(_("Attendance Days"), color="#16a34a")
        self.rest_card = DotProgressCard(_("Rest Days"), color="#ef4444")
        summary_grid.addWidget(self.monthly_hours_card, 0, 0)
        summary_grid.addWidget(self.overtime_card, 0, 1)
        summary_grid.addWidget(self.attendance_card, 0, 2)
        summary_grid.addWidget(self.rest_card, 0, 3)
        root.addLayout(summary_grid)

        charts = QGridLayout()
        charts.setHorizontalSpacing(12)
        charts.setVerticalSpacing(12)
        self.trend_chart = self._chart_card(_("Work Hours Trend"))
        self.average_chart = self._chart_card(_("Average Work Hours"))
        self.breakdown_chart = self._chart_card(_("Work Mode Breakdown"))
        self.daily_average_chart = self._chart_card(_("Daily Average"))
        charts.addWidget(self.trend_chart, 0, 0)
        charts.addWidget(self.average_chart, 0, 1)
        charts.addWidget(self.breakdown_chart, 1, 0)
        charts.addWidget(self.daily_average_chart, 1, 1)
        root.addLayout(charts, 1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("analytics_status_label")
        self.status_label.setProperty("role", "secondary")
        root.addWidget(self.status_label)

    def _chart_card(self, title: str) -> CardFrame:
        card = CardFrame(object_name="analytics_chart_frame")
        label = QLabel(title)
        label.setObjectName("analytics_chart_title_label")
        chart = ComboChart()
        card.chart = chart
        card.content_layout.addWidget(label)
        card.content_layout.addWidget(chart, 1)
        return card

    def _set_state(self, state: AnalyticsState) -> None:
        total = sum(value for _label, value in state.bundle.bar_data)
        overtime = max(total - 168.0, 0.0)
        days = len([value for _label, value in state.bundle.bar_data if value > 0])
        leave_days = len(state.bundle.leave_indices)
        progress = total / 168.0 if total > 0 else 0.0
        self.monthly_hours_card.set_value(
            f"{total:.1f}{_('h')}",
            _("of monthly goal"),
            progress,
        )
        self.overtime_value_label.setText(f"{overtime:.1f}{_('h')}")
        self.overtime_caption_label.setText(_("vs previous period"))
        self.attendance_card.set_value(f"{days}", _("tracked days"), min(days, 12), 12)
        self.rest_card.set_value(f"{leave_days}", _("leave days"), min(leave_days, 12), 12)
        for card in (
            self.trend_chart,
            self.average_chart,
            self.breakdown_chart,
            self.daily_average_chart,
        ):
            card.chart.set_data(state.bundle, mode="bar")

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
    ) -> None:
        super().__init__(parent)
        self.setObjectName("reports_page_widget")
        self._view_model = view_model
        self._selected_day = selected_day
        self._states: dict[str, ReportEditorState] = {}
        self._saved_content: dict[str, str] = {}
        self._last_error: AppError | None = None
        self._build_ui()

    @property
    def last_error(self) -> AppError | None:
        return self._last_error

    @property
    def has_unsaved_changes(self) -> bool:
        current = self._current_type()
        return self.editor.toPlainText() != self._saved_content.get(current, "")

    def refresh(self, selected_day: date | None = None) -> bool:
        if selected_day is not None:
            self._selected_day = selected_day
        if self._view_model is None:
            self.status_label.setText(_("Reports are not configured."))
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
            self.status_label.setText(_("Ready"))
        return ok

    def copy_markdown(self) -> None:
        QApplication.clipboard().setText(self.editor.toPlainText())
        self.status_label.setText(_("Copied"))

    def export_markdown(self, destination: Path) -> bool:
        if self._view_model is None:
            return False
        result = self._view_model.export_markdown(destination, self.editor.toPlainText())
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return False
        self.status_label.setText(_("Exported Markdown"))
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
            )
        )
        self.report_type_control.value_changed.connect(lambda _value: self._render_current())
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
        self.previous_period_button.setProperty("variant", "ghost")
        self.next_period_button = QPushButton(">")
        self.next_period_button.setObjectName("next_report_period_button")
        self.next_period_button.setProperty("variant", "ghost")
        period_row.addWidget(self.period_title_label, 1)
        period_row.addWidget(self.previous_period_button)
        period_row.addWidget(self.next_period_button)
        editor_card.content_layout.addLayout(period_row)

        report_row = QHBoxLayout()
        report_title = QLabel(_("Report"))
        report_title.setObjectName("report_title_label")
        self.templates_button = QPushButton(_("Templates"))
        self.templates_button.setObjectName("templates_button")
        self.templates_button.setProperty("variant", "outline")
        self.templates_button.clicked.connect(self._save_template_current)
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
        self.tip_label = QLabel(_("Tip: Click AI Assist to generate a draft based on your time logs."))
        self.tip_label.setObjectName("report_tip_label")
        self.tip_label.setProperty("role", "secondary")
        ai_row.addWidget(self.ai_assist_button)
        ai_row.addWidget(self.tip_label, 1)
        editor_card.content_layout.addLayout(ai_row)

        bottom = QHBoxLayout()
        self.copy_button = QPushButton(_("Copy"))
        self.copy_button.setObjectName("copy_report_button")
        self.copy_button.clicked.connect(self.copy_markdown)
        self.save_button = QPushButton(_("Save Report"))
        self.save_button.setObjectName("save_report_button")
        self.save_button.setProperty("variant", "primary")
        self.save_button.clicked.connect(self._save_current)
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
        root.addWidget(self.status_label)

    def _current_type(self) -> str:
        return self.report_type_control.value or "daily"

    def _render_current(self) -> None:
        report_type = self._current_type()
        state = self._states.get(report_type)
        if state is None:
            return
        self.period_title_label.setText(_period_label(state))
        self.editor.setPlainText(state.content)
        self.history_panel.set_selected_period(state.period_start, state.period_end)
        self._refresh_history()

    def _save_current(self) -> None:
        if self._view_model is None:
            return
        report_type = self._current_type()
        state = self._states.get(report_type)
        if state is None:
            self._set_error(ValidationError("report_not_loaded", "report_not_loaded"))
            return
        result = self._view_model.save(state, self.editor.toPlainText())
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return
        self._states[report_type] = result.value
        self._saved_content[report_type] = result.value.content
        self.status_label.setText(_("Report saved."))
        self._refresh_history()

    def _save_template_current(self) -> None:
        if self._view_model is None:
            return
        result = self._view_model.save_template(self._current_type(), self.editor.toPlainText())
        if not result.ok:
            self._set_error(result.error)
            return
        self.status_label.setText(_("Template saved."))

    def _rewrite_current(self) -> None:
        if self._view_model is None:
            return
        state = self._states.get(self._current_type())
        if state is None:
            self._set_error(ValidationError("report_not_loaded", "report_not_loaded"))
            return
        result = self._view_model.rewrite(state, self.editor.toPlainText())
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return
        self.editor.setPlainText(result.value)
        self.status_label.setText(_("Rewritten"))

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
                label=_period_range_label(item.period_start, item.period_end),
                content=item.content,
                saved=item.saved,
            )
            for item in result.value
        )

    def _select_history_item(self, item: ReportHistoryDisplayItem) -> None:
        if not self._view_model:
            return
        state = ReportEditorState(
            user_id=item.user_id,
            report_type=item.report_type,
            period_start=item.period_start,
            period_end=item.period_end,
            content=item.content,
            saved=True,
        )
        self._states[item.report_type] = state
        self._saved_content[item.report_type] = state.content
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
        self._last_error = error
        self.status_label.setText(display_error_message(error))


class SettingsPage(QWidget):
    def __init__(
        self,
        workflow: SettingsWorkflowWithDialog | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settings_page_widget")
        self._workflow = workflow
        self.embedded_settings: QWidget | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if workflow is None or not hasattr(workflow, "create_dialog"):
            placeholder = QLabel(_("Settings are not configured."))
            placeholder.setObjectName("settings_placeholder_label")
            placeholder.setProperty("role", "secondary")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(placeholder, 1)
            return
        self.embedded_settings = workflow.create_dialog(self)
        self.embedded_settings.setWindowFlags(Qt.WindowType.Widget)
        if hasattr(self.embedded_settings, "close_button"):
            self.embedded_settings.close_button.setVisible(False)
        layout.addWidget(self.embedded_settings)
        self.embedded_settings.show()

    def refresh(self) -> bool:
        if self.embedded_settings is None or not hasattr(self.embedded_settings, "refresh"):
            return False
        return bool(self.embedded_settings.refresh())


def _period_label(state: ReportEditorState) -> str:
    if state.period_start == state.period_end:
        return state.period_start.strftime("%B %-d, %Y") if _supports_dash_day() else state.period_start.strftime("%B %d, %Y")
    return _period_range_label(state.period_start, state.period_end)


def _period_range_label(start: date, end: date) -> str:
    if start.year == end.year and start.month == end.month:
        return f"{start.strftime('%B')} {start.day} - {end.strftime('%B')} {end.day}, {end.year}"
    return f"{start.strftime('%b')} {start.day} - {end.strftime('%b')} {end.day}, {end.year}"


def _supports_dash_day() -> bool:
    try:
        date.today().strftime("%-d")
    except ValueError:
        return False
    return True


def add_months(first_day: date, months: int) -> date:
    month_index = first_day.month - 1 + months
    year = first_day.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def shift_period(day: date, report_type: str, direction: int) -> date:
    if report_type == "daily":
        return day + timedelta(days=direction)
    if report_type == "weekly":
        return day + timedelta(days=direction * 7)
    shifted = add_months(day.replace(day=1), direction)
    last = monthrange(shifted.year, shifted.month)[1]
    return shifted.replace(day=min(day.day, last))
