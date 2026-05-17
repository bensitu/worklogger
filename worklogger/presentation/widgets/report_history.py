"""Report history panel widget."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget

from worklogger.infrastructure.i18n import _
from worklogger.presentation.widgets._style import refresh_style
from worklogger.presentation.widgets.card import CardFrame


@dataclass(frozen=True)
class ReportHistoryDisplayItem:
    report_id: int | None
    user_id: int
    report_type: str
    period_start: date
    period_end: date
    label: str
    content: str = ""
    saved: bool = False


class ReportHistoryPanel(CardFrame):
    item_selected = Signal(object)
    export_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, object_name="report_history_frame")
        self._items: tuple[ReportHistoryDisplayItem, ...] = ()
        self._buttons: dict[int, QPushButton] = {}
        self._selected_key = -1

        title = QLabel(_("Report History"))
        title.setObjectName("report_history_title_label")
        self.content_layout.addWidget(title)

        self.search_line_edit = QLineEdit()
        self.search_line_edit.setObjectName("report_search_line_edit")
        self.search_line_edit.setPlaceholderText(_("Search reports..."))
        self.search_line_edit.textChanged.connect(self._render)
        self.content_layout.addWidget(self.search_line_edit)

        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("report_history_scroll_area_widget")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_widget = QWidget()
        self.scroll_widget.setObjectName("report_history_content_widget")
        self.scroll_layout = QVBoxLayout(self.scroll_widget)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(8)
        self.scroll_area.setWidget(self.scroll_widget)
        self.content_layout.addWidget(self.scroll_area, 1)

        self.export_button = QPushButton(_("Export Reports"))
        self.export_button.setObjectName("export_reports_button")
        self.export_button.setProperty("variant", "outline")
        self.export_button.clicked.connect(self.export_requested.emit)
        self.content_layout.addWidget(self.export_button)

    def set_items(self, items: Iterable[ReportHistoryDisplayItem]) -> None:
        self._items = tuple(items)
        self._render()

    def set_selected_period(self, start: date, end: date) -> None:
        self._selected_key = hash((start, end))
        for button in self._buttons.values():
            selected = button.property("history_key") == self._selected_key
            button.setProperty("active", selected)
            refresh_style(button)

    def _render(self) -> None:
        while self.scroll_layout.count():
            item = self.scroll_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._buttons = {}

        query = self.search_line_edit.text().strip().lower()
        visible = [
            item
            for item in self._items
            if not query or query in item.label.lower()
        ]
        if not visible:
            label = QLabel(_("No saved reports"))
            label.setObjectName("empty_report_history_label")
            label.setProperty("role", "secondary")
            self.scroll_layout.addWidget(label)
            self.scroll_layout.addStretch(1)
            return

        current_month = ""
        for index, item in enumerate(visible):
            month = item.period_start.strftime("%B %Y")
            if month != current_month:
                current_month = month
                heading = QLabel(month)
                heading.setObjectName("report_history_month_label")
                self.scroll_layout.addWidget(heading)
            button = QPushButton(_history_label(item))
            button.setObjectName("report_history_item_button")
            button.setProperty("nav_item", True)
            key = hash((item.period_start, item.period_end))
            button.setProperty("history_key", key)
            button.setProperty("active", key == self._selected_key)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, selected=item: self.item_selected.emit(selected))
            self._buttons[index] = button
            self.scroll_layout.addWidget(button)
        self.scroll_layout.addStretch(1)


def _history_label(item: ReportHistoryDisplayItem) -> str:
    marker = f"  {_('Saved')}" if item.saved else ""
    return f"{item.label}{marker}"
