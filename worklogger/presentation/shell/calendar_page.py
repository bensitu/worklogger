"""Calendar recording page."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
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
from worklogger.presentation.date_labels import day_label


class CalendarPage(QWidget):
    previous_month_requested = Signal()
    next_month_requested = Signal()
    today_requested = Signal()
    search_requested = Signal()
    entry_selected = Signal(object)
    event_selected = Signal(object)
    entry_delete_requested = Signal(object)
    event_delete_requested = Signal(object)
    entry_actions_requested = Signal(object, object)

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
        self.entry_panel.new_record()

    def set_time_entries(self, entries, events):
        self.selected_date_label.setText(day_label(self.entry_panel.view_model.draft.day))
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
        self.previous_month_button.setProperty("variant", "outline")
        self.previous_month_button.setToolTip(_("Previous month"))
        self.previous_month_button.setAccessibleName(_("Previous month"))
        set_button_icon(self.previous_month_button, "chevron-left")
        self.previous_month_button.setText("")
        self.previous_month_button.clicked.connect(self.previous_month_requested.emit)
        self.month_title_label = QLabel("")
        self.month_title_label.setObjectName("calendar_month_title_label")
        self.month_title_label.setProperty("role", "title")
        self.month_title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.next_month_button = QPushButton(">")
        self.next_month_button.setObjectName("next_month_button")
        self.next_month_button.setProperty("variant", "outline")
        self.next_month_button.setToolTip(_("Next month"))
        self.next_month_button.setAccessibleName(_("Next month"))
        set_button_icon(self.next_month_button, "chevron-right")
        self.next_month_button.setText("")
        self.next_month_button.clicked.connect(self.next_month_requested.emit)
        self.today_button = QPushButton(_("Today"))
        self.today_button.setObjectName("today_button")
        self.today_button.clicked.connect(self.today_requested.emit)
        self.search_button = QPushButton()
        self.search_button.setObjectName("search_records_button")
        self.search_button.setToolTip(_("Search records"))
        self.search_button.setAccessibleName(_("Search records"))
        set_button_icon(self.search_button, "search")
        self.search_button.setVisible(self.entry_panel.view_model.search_available)
        self.search_button.clicked.connect(self.search_requested.emit)
        shortcut = QShortcut(QKeySequence.StandardKey.Find, self)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(lambda: self.search_requested.emit() if self.entry_panel.view_model.search_available else None)
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
        header.addWidget(self.search_button)
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

        right = QFrame()
        self.right_panel = right
        right.setFixedWidth(300)
        right.setObjectName("calendar_right_panel_frame")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 0, 0, 0)
        right_layout.setSpacing(10)
        self.selected_date_label = QLabel()
        self.selected_date_label.setObjectName("selected_calendar_date_label")
        self.selected_date_label.setProperty("role", "section_heading")
        self.selected_date_label.setWordWrap(True)
        right_layout.addWidget(self.selected_date_label)
        self.entry_panel.layout().removeWidget(self.entry_panel.time_tabs)
        right_layout.addWidget(self.entry_panel.time_tabs)
        self.details_scroll = QScrollArea()
        self.details_scroll.setObjectName("calendar_details_scroll_widget")
        self.details_scroll.setWidgetResizable(True)
        self.details_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.details_scroll.setMinimumHeight(60)
        self.details_scroll.setWidget(self.entry_panel)
        self.stats_panel.setVisible(False)
        right_layout.addWidget(self.details_scroll)
        self.entry_panel.layout().removeWidget(self.entry_panel.actions_widget)
        right_layout.addWidget(self.entry_panel.actions_widget)
        self.entry_panel.busy_changed.connect(lambda busy: self.entry_panel.actions_widget.setEnabled(not busy))
        self.entry_panel.busy_changed.connect(lambda busy: self.entry_panel.time_tabs.setEnabled(not busy))
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
        self.records_widget.entry_actions_requested.connect(self.entry_actions_requested.emit)
        self.records_widget.event_selected.connect(self.event_selected.emit)
        self.records_widget.event_delete_requested.connect(self.event_delete_requested.emit)
        self.records_scroll.setWidget(self.records_widget)
        right_layout.addWidget(self.records_scroll, 1)
        content.addWidget(right, 0)
        self.entry_panel.installEventFilter(self)
        self.entry_panel.editor_layout_changed.connect(self._fit_editor)
        QTimer.singleShot(0, self, self._fit_editor)

    def _fit_editor(self):
        self.entry_panel.layout().invalidate()
        self.entry_panel.layout().activate()
        layout = self.right_panel.layout()
        visible = [layout.itemAt(index).widget() for index in range(layout.count())
                   if layout.itemAt(index).widget() is not None and not layout.itemAt(index).widget().isHidden()]
        fixed = sum(widget.height() for widget in visible if widget not in (self.details_scroll, self.records_scroll))
        margins = layout.contentsMargins()
        available = max(60, self.right_panel.height() - margins.top() - margins.bottom()
                        - layout.spacing() * max(0, len(visible) - 1) - fixed - self.records_scroll.minimumHeight())
        content = self.entry_panel.content_input
        content.setFixedHeight(max(48, min(76, content.height() + available - self.entry_panel.sizeHint().height() - 4)))
        preferred = max(60, self.entry_panel.sizeHint().height() + 4)
        self.details_scroll.setMinimumHeight(min(available, preferred))
        self.details_scroll.setMaximumHeight(preferred)
        layout.activate()

    def eventFilter(self, watched, event):
        if watched is self.entry_panel and event.type() in (QEvent.Type.LayoutRequest, QEvent.Type.StyleChange, QEvent.Type.FontChange):
            QTimer.singleShot(0, self, self._fit_editor)
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "right_panel"):
            self.right_panel.setFixedWidth(max(300, min(380, round((self.width() - 52) * 0.28))))
            QTimer.singleShot(0, self, self._fit_editor)
