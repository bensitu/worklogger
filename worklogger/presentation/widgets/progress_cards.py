"""Dashboard metric cards composed from reusable layouts and progress visuals."""

from PySide6.QtWidgets import QWidget

from worklogger.presentation.widgets.progress_visuals import (
    DonutGauge,
    OvertimeComparisonChart as OvertimeComparisonChart,
    ProgressDots,
)
from worklogger.presentation.widgets.summary_card import SummaryCard, SummaryValueLabel as SummaryValueLabel


class DonutProgressCard(SummaryCard):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        gauge = DonutGauge()
        super().__init__(title, visual=gauge, parent=parent, object_name="donut_progress_card_frame")
        self.gauge = gauge

    def set_value(self, value: str, caption: str, progress: float) -> None:
        self.value_label.setText(value)
        self.caption_label.setText(caption)
        self.gauge.set_progress(progress)


class DotProgressCard(SummaryCard):
    def __init__(self, title: str, *, color: str | None = None, color_role: str = "success",
                 parent: QWidget | None = None) -> None:
        super().__init__(title, parent=parent, object_name="dot_progress_card_frame")
        self.dots_widget = ProgressDots(color=color, color_role=color_role)
        self.content_layout.addWidget(self.dots_widget)

    def set_value(self, value: str, caption: str, filled: int, total: int = 12) -> None:
        self.value_label.setText(value)
        self.caption_label.setText(caption)
        self.dots_widget.set_progress(filled, total)

