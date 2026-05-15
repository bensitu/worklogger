"""Analytics dialog."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from worklogger.domain.shared.errors import AppError
from worklogger.infrastructure.i18n import _
from worklogger.presentation.viewmodels import AnalyticsState, AnalyticsViewModel
from worklogger.presentation.widgets import ComboChart


class AnalyticsDialog(QDialog):
    def __init__(
        self,
        view_model: AnalyticsViewModel,
        selected_day: date,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._view_model = view_model
        self._selected_day = selected_day
        self._state: AnalyticsState | None = None
        self._last_error: AppError | None = None
        self.setObjectName("analytics_dialog")
        self.setWindowTitle(_("Analytics"))
        self._build_ui()

    @property
    def last_error(self) -> AppError | None:
        return self._last_error

    def refresh(self) -> bool:
        result = self._view_model.load(
            year=self.year_input.value(),
            month=self.month_input.value(),
            scope=self.scope_combo.currentData(),
            metric=self.metric_combo.currentData(),
            chart_mode=self.chart_combo.currentData(),
            include_leaves=self.include_leaves_check.isChecked(),
        )
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return False
        self.set_state(result.value)
        self.status_label.setText(_("Ready"))
        return True

    def set_state(self, state: AnalyticsState) -> None:
        self._state = state
        self.chart.set_data(state.bundle, mode=state.chart_mode)
        total = sum(value for _label, value in state.bundle.bar_data)
        self.summary_label.setText(
            _("Total: {hours:.1f}h").format(hours=total)
        )

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        controls = QHBoxLayout()
        self.year_input = QSpinBox()
        self.year_input.setRange(1970, 9999)
        self.year_input.setValue(self._selected_day.year)
        self.month_input = QSpinBox()
        self.month_input.setRange(1, 12)
        self.month_input.setValue(self._selected_day.month)
        self.scope_combo = QComboBox()
        self.scope_combo.addItem(_("Monthly"), "monthly")
        self.scope_combo.addItem(_("Quarterly"), "quarterly")
        self.scope_combo.addItem(_("Annual"), "annual")
        self.metric_combo = QComboBox()
        self.metric_combo.addItem(_("Work hours"), "hours")
        self.metric_combo.addItem(_("Average"), "average")
        self.chart_combo = QComboBox()
        self.chart_combo.addItem(_("Bar"), "bar")
        self.chart_combo.addItem(_("Line"), "line")
        self.include_leaves_check = QCheckBox(_("Show leaves"))
        self.include_leaves_check.setChecked(True)
        controls.addWidget(QLabel(_("Year")))
        controls.addWidget(self.year_input)
        controls.addWidget(QLabel(_("Month")))
        controls.addWidget(self.month_input)
        controls.addWidget(self.scope_combo)
        controls.addWidget(self.metric_combo)
        controls.addWidget(self.chart_combo)
        controls.addWidget(self.include_leaves_check)
        controls.addStretch(1)
        root.addLayout(controls)

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("analytics_summary_label")
        root.addWidget(self.summary_label)

        self.chart = ComboChart()
        root.addWidget(self.chart, 1)

        tools = QHBoxLayout()
        self.refresh_button = QPushButton(_("Refresh"))
        self.export_csv_button = QPushButton(_("Export CSV"))
        self.export_pdf_button = QPushButton(_("Export PDF"))
        self.close_button = QPushButton(_("Close"))
        self.status_label = QLabel("")
        tools.addWidget(self.refresh_button)
        tools.addWidget(self.export_csv_button)
        tools.addWidget(self.export_pdf_button)
        tools.addWidget(self.status_label, 1)
        tools.addWidget(self.close_button)
        root.addLayout(tools)

        self.refresh_button.clicked.connect(self.refresh)
        self.export_csv_button.clicked.connect(self._choose_csv_path)
        self.export_pdf_button.clicked.connect(self._choose_pdf_path)
        self.close_button.clicked.connect(self.accept)

    def export_csv(self, destination: Path) -> bool:
        if self._state is None and not self.refresh():
            return False
        assert self._state is not None
        result = self._view_model.export_csv(destination, self._state)
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return False
        self.status_label.setText(_("Exported CSV"))
        return True

    def export_pdf(self, destination: Path) -> bool:
        if self._state is None and not self.refresh():
            return False
        assert self._state is not None
        result = self._view_model.export_pdf(destination, self._state)
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return False
        self.status_label.setText(_("Exported PDF"))
        return True

    def _choose_csv_path(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            _("Export CSV"),
            "analytics.csv",
            _("CSV files (*.csv)"),
        )
        if path:
            self.export_csv(Path(path))

    def _choose_pdf_path(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            _("Export PDF"),
            "analytics.pdf",
            _("PDF files (*.pdf)"),
        )
        if path:
            self.export_pdf(Path(path))

    def _set_error(self, error: AppError | None) -> None:
        self._last_error = error
        self.status_label.setText(error.message if error is not None else _("Unknown error"))
