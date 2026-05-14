"""Stats panel Qt widget."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from worklogger.infrastructure.i18n import _
from worklogger.presentation.viewmodels.stats import StatsPanelState


class StatsPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("stats_panel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("stat_card")
        grid = QGridLayout(card)
        grid.setContentsMargins(10, 8, 10, 8)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        layout.addWidget(card)

        self._values: dict[str, QLabel] = {}
        rows = (
            ("total_hours", _("Total hours")),
            ("overtime_hours", _("Overtime")),
            ("average_hours", _("Average")),
            ("work_days", _("Work days")),
            ("leave_days", _("Leave days")),
            ("monthly_target_hours", _("Monthly target")),
        )
        for index, (key, label_text) in enumerate(rows):
            key_label = QLabel(label_text)
            key_label.setObjectName("stat_key")
            value_label = QLabel("")
            value_label.setObjectName("stat_val")
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._values[key] = value_label
            grid.addWidget(key_label, index, 0)
            grid.addWidget(value_label, index, 1)

        self.progress = QProgressBar()
        self.progress.setObjectName("target_progress")
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(True)
        grid.addWidget(self.progress, len(rows), 0, 1, 2)

    def value_text(self, key: str) -> str:
        return self._values[key].text()

    def set_state(self, state: StatsPanelState) -> None:
        self._values["total_hours"].setText(f"{state.total_hours:.1f}{_('h')}")
        self._values["overtime_hours"].setText(f"{state.overtime_hours:.1f}{_('h')}")
        self._values["average_hours"].setText(f"{state.average_hours:.1f}{_('h')}")
        self._values["work_days"].setText(str(state.work_days))
        self._values["leave_days"].setText(str(state.leave_days))
        self._values["monthly_target_hours"].setText(
            f"{state.monthly_target_hours:.1f}{_('h')}"
        )
        self.progress.setValue(round(state.target_progress * 100))
