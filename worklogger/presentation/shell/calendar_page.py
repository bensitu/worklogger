"""Calendar recording page."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from worklogger.infrastructure.i18n import _
from worklogger.presentation.widgets import (
    CalendarView,
    StatsPanel,
)
from worklogger.presentation.widgets.icons import set_button_icon
from worklogger.presentation.widgets.time_entries import TimeEntryPanel
from worklogger.presentation.widgets.time_entry_history import TimeEntryHistory


class CalendarPage(QWidget):
    previous_month_requested = Signal()
    next_month_requested = Signal()
    today_requested = Signal()
    entry_selected = Signal(object)
    event_selected = Signal(object)
    entry_delete_requested = Signal(object)
    event_delete_requested = Signal(object)

    def __init__(
        self,
        *,
        calendar_view: CalendarView,
        entry_panel: TimeEntryPanel,
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

    def _new_time_record(self):
        if self.entry_panel.new_record():
            QTimer.singleShot(0, self, lambda: self.details_scroll.ensureWidgetVisible(self.entry_panel.start_input, 0, 8))

    def set_time_entries(self, entries, events):
        self.records_widget.set_entries(entries, events)

    def set_selected_entry(self, entry_id):
        self.records_widget.set_selected_entry(entry_id)

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
        self.add_entry_button = QPushButton(_("New time record"))
        self.add_entry_button.clicked.connect(self._new_time_record)
        self.notes_button = QPushButton(_("Notes"))
        self.notes_button.setObjectName("daily_notes_button")
        self.notes_button.setToolTip(_("Notes"))
        set_button_icon(self.notes_button, "file-text")
        self.add_entry_button.setObjectName("add_entry_button")
        self.add_entry_button.setProperty("variant", "primary")
        set_button_icon(self.add_entry_button, "plus")
        self.add_entry_button.setToolTip(_("New time record"))
        header.addWidget(self.previous_month_button)
        header.addStretch(1)
        header.addWidget(self.month_title_label)
        header.addStretch(1)
        header.addWidget(self.next_month_button)
        header.addWidget(self.today_button)
        header.addWidget(self.add_entry_button)
        header.addWidget(self.notes_button)
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
        self.details_scroll.setFixedWidth(280)
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
        self.records_widget = TimeEntryHistory(self.entry_panel.view_model)
        self.records_layout = self.records_widget.rows
        self.records_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.records_widget.entry_selected.connect(self.entry_selected.emit)
        self.records_widget.entry_delete_requested.connect(self.entry_delete_requested.emit)
        self.records_widget.event_selected.connect(self.event_selected.emit)
        self.records_widget.event_delete_requested.connect(self.event_delete_requested.emit)
        self.records_scroll.setWidget(self.records_widget)
        right_layout.addWidget(self.records_scroll, 1)
        content.addWidget(self.details_scroll)
