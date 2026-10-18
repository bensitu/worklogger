"""Report history panel widget."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from PySide6.QtCore import QEvent, QSize, Qt, Signal, QTimer, QSignalBlocker
from PySide6.QtGui import QAbstractTextDocumentLayout, QAction, QPainter, QPalette, QTextDocument
from PySide6.QtWidgets import (
    QApplication, QComboBox, QLabel, QLayout, QLineEdit, QPushButton, QScrollArea, QSizePolicy, QProgressBar,
    QStyle, QStyleOptionButton, QVBoxLayout, QWidget,
)

from worklogger.infrastructure.i18n import _
from worklogger.presentation.theme.widget_style import set_style_property
from worklogger.presentation.widgets.card import CardFrame
from worklogger.presentation.date_labels import month_label
from worklogger.presentation.widgets.icons import set_button_icon, ui_icon
from worklogger.presentation.widgets.hover_delete_button import HoverDeleteButton
from worklogger.domain.reporting.history import ReportHistoryFilter, ReportSort
from worklogger.presentation.widgets.date_range import DateRangeControls
from worklogger.presentation.date_labels import period_range_label


class ReportHistoryButton(HoverDeleteButton):
    def __init__(self, item: ReportHistoryDisplayItem, parent: QWidget | None = None, *, allow_delete=True) -> None:
        super().__init__(_history_label(item), parent, deletable=allow_delete and item.report_id is not None,
                         delete_label=_("Delete report"))
        self._base_label = _history_label(item)
        self._document = QTextDocument(self)
        self._document.setDocumentMargin(0)
        self._document.setPlainText(self.text())
        self._measurement_document = QTextDocument(self)
        self._measurement_document.setDocumentMargin(0)
        self._height_cache = {}
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setToolTip(self.text())
        self.setAccessibleName(self.text() + (" " + _("Saved") if item.saved else ""))

    def sizeHint(self) -> QSize:
        return QSize(180, self.heightForWidth(180))

    def minimumSizeHint(self) -> QSize:
        return QSize(80, 60)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        # Layout probes must not reflow the document used for painting.
        key = (width, self.font().toString(), self.text(), self._text_margins())
        if key in self._height_cache:
            return self._height_cache[key]
        document = self._measurement_document
        document.setDefaultFont(self.font())
        document.setPlainText(self.text())
        document.setTextWidth(max(1, width - self._text_margins()))
        height = max(60, round(document.size().height()) + 20)
        if len(self._height_cache) >= 8:
            self._height_cache.clear()
        self._height_cache[key] = height
        return height

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)
        self._document.setDefaultFont(self.font())
        self._document.setTextWidth(max(1, self.width() - self._text_margins()))
        self.setMinimumHeight(self.heightForWidth(self.width()))

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.text = ""
        self.style().drawControl(QStyle.ControlElement.CE_PushButton, option, painter, self)
        context = QAbstractTextDocumentLayout.PaintContext()
        context.palette = self.palette()
        group = QPalette.ColorGroup.Active if self.isEnabled() else QPalette.ColorGroup.Disabled
        context.palette.setColor(QPalette.ColorRole.Text, self.palette().color(group, QPalette.ColorRole.ButtonText))
        painter.save()
        painter.translate(12, (self.height() - self._document.size().height()) / 2)
        self._document.documentLayout().draw(painter, context)
        painter.restore()
        painter.end()

    def _text_margins(self):
        return 52 if self._deletable else 24

    def set_current(self, current):
        text = self._base_label + "\n" + (_("Open in editor") if current else _("Saved"))
        if self.property("active") == current and self.text() == text:
            return
        set_style_property(self, "active", current)
        self.setText(text)
        self.setAccessibleName(text)
        self._document.setPlainText(text)
        self._document.setDefaultFont(self.font())
        self._document.setTextWidth(max(1, self.width() - self._text_margins()))
        self.setToolTip(text)
        self.setMinimumHeight(self.heightForWidth(max(80, self.width())))


@dataclass(frozen=True)
class ReportHistoryDisplayItem:
    report_id: int | None
    user_id: int
    report_type: str
    period_start: date
    period_end: date
    label: str
    saved: bool = False
    created_at: datetime | None = None
    revision: int = 0
    updated_at: datetime | None = None


class ReportHistoryPanel(CardFrame):
    item_selected = Signal(object)
    export_requested = Signal()
    delete_requested = Signal(object)
    filters_changed = Signal()
    query_requested = Signal()
    more_requested = Signal()

    def __init__(self, parent: QWidget | None = None, *, allow_delete=True, show_export=True, day=None) -> None:
        super().__init__(parent, object_name="report_history_frame")
        self.content_layout.setSpacing(8)
        self._items: tuple[ReportHistoryDisplayItem, ...] = ()
        self._buttons: dict[int, QPushButton] = {}
        self._selected_report_id: int | None = None
        self._allow_delete = allow_delete
        self._hovered_button = None
        self._report_type = None
        self.next_cursor = None
        self._render_key = None
        self._loading = False
        self._count_text = ""
        self._loading_timer = QTimer(self)
        self._loading_timer.setSingleShot(True)
        self._loading_timer.setInterval(150)
        self._loading_timer.timeout.connect(self._show_loading)

        title = QLabel(_("Saved reports"))
        title.setObjectName("report_history_title_label")
        self.content_layout.addWidget(title)
        self.scope_label = QLabel()
        self.scope_label.setProperty("role", "secondary")
        self.scope_label.setWordWrap(True)
        self.content_layout.addWidget(self.scope_label)

        self.search_line_edit = QLineEdit()
        self.search_line_edit.setObjectName("report_search_line_edit")
        self.search_line_edit.setPlaceholderText(_("Search reports..."))
        self.search_line_edit.setAccessibleName(_("Search reports..."))
        self.search_line_edit.setClearButtonEnabled(True)
        self.search_line_edit.setMaxLength(256)
        self.search_line_edit.addAction(
            QAction(ui_icon("search"), _("Search reports..."), self.search_line_edit),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self._search_timer.timeout.connect(self.query_requested.emit)
        self.search_line_edit.textChanged.connect(self._filters_changed)
        self.content_layout.addWidget(self.search_line_edit)
        self.date_range = DateRangeControls(day or date.today())
        self.date_range.range_changed.connect(self._filters_changed)
        self.content_layout.addWidget(self.date_range)
        self.sort_input = QComboBox()
        self.sort_input.setAccessibleName(_("Sort order"))
        for label, value in ((_("Report date: newest first"), ReportSort.DATE_DESC),
                             (_("Report date: oldest first"), ReportSort.DATE_ASC),
                             (_("First saved: newest first"), ReportSort.SAVED_DESC),
                             (_("First saved: oldest first"), ReportSort.SAVED_ASC)):
            self.sort_input.addItem(label, value)
        self.sort_input.currentIndexChanged.connect(self._filters_changed)
        self.content_layout.addWidget(self.sort_input)
        self.count_label = QLabel()
        self.count_label.setProperty("role", "secondary")
        self.count_label.setWordWrap(True)
        self.content_layout.addWidget(self.count_label)
        self.loading_bar = QProgressBar()
        self.loading_bar.setRange(0, 0)
        self.loading_bar.setTextVisible(False)
        self.loading_bar.setFixedHeight(6)
        self.loading_bar.setAccessibleName(_("Loading..."))
        policy = self.loading_bar.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.loading_bar.setSizePolicy(policy)
        self.loading_bar.hide()
        self.content_layout.addWidget(self.loading_bar)

        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("report_history_scroll_area_widget")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_widget = QWidget()
        self.scroll_widget.setObjectName("report_history_content_widget")
        self.scroll_layout = QVBoxLayout(self.scroll_widget)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(8)
        self.scroll_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.scroll_area.setWidget(self.scroll_widget)
        self.content_layout.addWidget(self.scroll_area, 1)
        self.more_button = QPushButton(_("Load more"))
        set_button_icon(self.more_button, "chevron-down")
        self.more_button.clicked.connect(self.more_requested.emit)
        self.more_button.hide()
        self.content_layout.addWidget(self.more_button)

        self.export_button = QPushButton(_("Export Reports"))
        self.export_button.setObjectName("export_reports_button")
        self.export_button.setProperty("variant", "outline")
        set_button_icon(self.export_button, "file-output")
        self.export_button.clicked.connect(self.export_requested.emit)
        self.content_layout.addWidget(self.export_button)
        self.export_button.setVisible(show_export)
        self.set_context("daily", day or date.today())

    def showEvent(self, event):
        super().showEvent(event)
        QApplication.instance().installEventFilter(self)

    def hideEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        super().hideEvent(event)

    def _filters_changed(self, *_args):
        self.filters_changed.emit()
        self._search_timer.start()

    def criteria(self):
        start, end = self.date_range.bounds()
        return ReportHistoryFilter(self._report_type, start, end, self.search_line_edit.text().strip(),
                                   self.sort_input.currentData())

    def set_context(self, report_type, day, *, reset=False, week_start_monday=False):
        if report_type != self._report_type or reset:
            modes = {"daily": ("week", "month", "year", "custom", "all"),
                     "weekly": ("month", "year", "custom", "all"),
                     "monthly": ("year", "custom", "all")}[report_type]
            with QSignalBlocker(self.date_range):
                self.date_range.week_start_monday = week_start_monday
                self.date_range.set_modes(modes, default="year" if report_type == "monthly" else "month", day=day)
        self._report_type = report_type
        self.set_report_type(report_type)

    def set_loading(self, loading):
        if self._loading == loading:
            return
        self._loading = loading
        self.more_button.setEnabled(not loading)
        if loading:
            self._loading_timer.start()
        else:
            self._loading_timer.stop()
            self.loading_bar.hide()
            self.more_button.setText(_("Load more"))
            self.count_label.setText(self._count_text)

    def _show_loading(self):
        if self._loading:
            self.loading_bar.show()
            self.more_button.setText(_("Loading..."))
            self.count_label.setText(_("Loading..."))

    def set_page(self, page, *, append=False):
        items = tuple(ReportHistoryDisplayItem(item.id, item.user_id, item.report_type,
            item.period_start, item.period_end, period_range_label(item.period_start, item.period_end),
            saved=True, created_at=item.created_at, revision=item.revision, updated_at=item.updated_at)
            for item in page.reports)
        self._items = self._items + items if append else items
        self.next_cursor = page.next_cursor
        render_key = (self._items, tuple(self._month(item) for item in self._items))
        if render_key != self._render_key:
            self._render(append_from=len(self._buttons) if append else 0)
            self._render_key = render_key
        self._count_text = _("{shown} of {total} reports").format(shown=len(self._items), total=page.total)
        self.count_label.setText(self._count_text)
        self.more_button.setVisible(page.next_cursor is not None)

    def set_report_type(self, report_type):
        caption = {"daily": _("Daily"), "weekly": _("Weekly"), "monthly": _("Monthly")}[report_type]
        self.scope_label.setText(_("{type} | This account").format(type=caption))
        self.scope_label.setToolTip(_("Saved reports for this account, not revisions of the open report."))

    def set_selected_report(self, report_id: int | None) -> None:
        self._selected_report_id = report_id
        for button in self._buttons.values():
            selected = report_id is not None and button.property("report_id") == report_id
            button.set_current(selected)

    def _render(self, *, append_from=0) -> None:
        self._search_timer.stop()
        self._hovered_button = None
        while not append_from and self.scroll_layout.count():
            item = self.scroll_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # Keep ownership until deletion so queued show events cannot create windows.
                widget.hide()
                widget.deleteLater()
        if not append_from:
            self._buttons = {}
        elif self.scroll_layout.count():
            self.scroll_layout.takeAt(self.scroll_layout.count() - 1)
        visible = self._items
        if not visible:
            label = QLabel(_("No saved reports"), self.scroll_widget)
            label.setObjectName("empty_report_history_label")
            label.setProperty("role", "secondary")
            self.scroll_layout.addWidget(label)
            self.scroll_layout.addStretch(1)
            return

        current_month = self._month(visible[append_from - 1]) if append_from else ""
        for index, item in enumerate(visible[append_from:], append_from):
            month = self._month(item)
            if month != current_month:
                current_month = month
                heading = QLabel(month, self.scroll_widget)
                heading.setObjectName("report_history_month_label")
                self.scroll_layout.addWidget(heading)
            button = ReportHistoryButton(item, self.scroll_widget, allow_delete=self._allow_delete)
            button.setObjectName("report_history_item_button")
            button.setProperty("report_id", item.report_id)
            button.set_current(item.report_id is not None and item.report_id == self._selected_report_id)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setMinimumHeight(button.heightForWidth(self.scroll_area.viewport().width()))
            button.clicked.connect(lambda _checked=False, selected=item: self._emit_item_action(self.item_selected, selected))
            button.delete_requested.connect(lambda selected=item: self._emit_item_action(self.delete_requested, selected))
            button.hovered.connect(self._track_hover)
            self._buttons[index] = button
            self.scroll_layout.addWidget(button)
        self.scroll_layout.addStretch(1)

    def _emit_item_action(self, signal, item):
        if not self._loading:
            signal.emit(item)

    def _month(self, item):
        if self.sort_input.currentData() in (ReportSort.DATE_ASC, ReportSort.DATE_DESC):
            return month_label(item.period_start)
        stamp = item.created_at
        if stamp is None:
            return _("Save time unavailable")
        stamp = stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp
        return month_label(stamp.astimezone().date())

    def _track_hover(self, button):
        self._hovered_button = button

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseMove and self.isVisible() and self._hovered_button is not None:
            button = self._hovered_button
            position = event.globalPosition().toPoint()
            button.update_delete_visibility(position)
            if not button.rect().contains(button.mapFromGlobal(position)):
                self._hovered_button = None
        return super().eventFilter(watched, event)


def _history_label(item: ReportHistoryDisplayItem) -> str:
    label = item.label
    if item.report_type == "weekly":
        label += "\n" + _("(Week {week})").format(week=item.period_start.isocalendar().week)
    if item.created_at is not None:
        stamp = item.created_at
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        label += "\n" + _("First saved: {time}").format(time=stamp.astimezone().strftime("%Y-%m-%d %H:%M:%S"))
    if item.report_id is not None:
        label += "\n" + _("Report #{report_id}").format(report_id=item.report_id)
    return label
