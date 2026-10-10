"""Report history panel widget."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timezone

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QAbstractTextDocumentLayout, QAction, QPainter, QPalette, QTextDocument
from PySide6.QtWidgets import (
    QApplication, QLabel, QLayout, QLineEdit, QPushButton, QScrollArea, QSizePolicy,
    QStyle, QStyleOptionButton, QVBoxLayout, QWidget,
)

from worklogger.infrastructure.i18n import _
from worklogger.presentation.widgets._style import refresh_style
from worklogger.presentation.widgets.card import CardFrame
from worklogger.presentation.date_labels import month_label
from worklogger.presentation.widgets.icons import set_button_icon, ui_icon
from worklogger.presentation.widgets.hover_delete_button import HoverDeleteButton
from worklogger.domain.reporting.export_selection import saved_report_order
from worklogger.domain.reporting.models import ReportProvenance


class ReportHistoryButton(HoverDeleteButton):
    def __init__(self, item: ReportHistoryDisplayItem, parent: QWidget | None = None, *, allow_delete=True) -> None:
        super().__init__(_history_label(item), parent, deletable=allow_delete and item.report_id is not None,
                         delete_label=_("Delete report"))
        self._base_label = _history_label(item)
        self._document = QTextDocument(self)
        self._document.setDocumentMargin(0)
        self._document.setPlainText(self.text())
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
        document = QTextDocument()
        document.setDocumentMargin(0)
        document.setDefaultFont(self.font())
        document.setPlainText(self.text())
        document.setTextWidth(max(1, width - self._text_margins()))
        return max(60, round(document.size().height()) + 20)

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
        if self.property("active"):
            context.palette.setColor(QPalette.ColorRole.Text, self.palette().color(QPalette.ColorRole.Highlight))
        painter.save()
        painter.translate(12, (self.height() - self._document.size().height()) / 2)
        self._document.documentLayout().draw(painter, context)
        painter.restore()
        painter.end()

    def _text_margins(self):
        return 52 if self._deletable else 24

    def set_current(self, current):
        self.setProperty("active", current)
        text = self._base_label + "\n" + (_("Open in editor") if current else _("Saved"))
        self.setText(text)
        self.setAccessibleName(text)
        self._document.setPlainText(text)
        self._document.setDefaultFont(self.font())
        self._document.setTextWidth(max(1, self.width() - self._text_margins()))
        self.setToolTip(text)
        self.setMinimumHeight(self.heightForWidth(max(80, self.width())))
        refresh_style(self)


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
    created_at: datetime | None = None
    revision: int = 0
    updated_at: datetime | None = None
    provenance: ReportProvenance = ReportProvenance()


class ReportHistoryPanel(CardFrame):
    item_selected = Signal(object)
    export_requested = Signal()
    delete_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None, *, allow_delete=True, show_export=True) -> None:
        super().__init__(parent, object_name="report_history_frame")
        self._items: tuple[ReportHistoryDisplayItem, ...] = ()
        self._buttons: dict[int, QPushButton] = {}
        self._selected_report_id: int | None = None
        self._allow_delete = allow_delete
        self._hovered_button = None

        title = QLabel(_("Saved reports"))
        title.setObjectName("report_history_title_label")
        self.content_layout.addWidget(title)
        self.scope_label = QLabel(_("This account | Newest saved first"))
        self.scope_label.setProperty("role", "secondary")
        self.scope_label.setWordWrap(True)
        self.content_layout.addWidget(self.scope_label)

        self.search_line_edit = QLineEdit()
        self.search_line_edit.setObjectName("report_search_line_edit")
        self.search_line_edit.setPlaceholderText(_("Search reports..."))
        self.search_line_edit.addAction(
            QAction(ui_icon("search"), _("Search reports..."), self.search_line_edit),
            QLineEdit.ActionPosition.LeadingPosition,
        )
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
        self.scroll_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.scroll_area.setWidget(self.scroll_widget)
        self.content_layout.addWidget(self.scroll_area, 1)

        self.export_button = QPushButton(_("Export Reports"))
        self.export_button.setObjectName("export_reports_button")
        self.export_button.setProperty("variant", "outline")
        set_button_icon(self.export_button, "file-output", accent=True)
        self.export_button.clicked.connect(self.export_requested.emit)
        self.content_layout.addWidget(self.export_button)
        self.export_button.setVisible(show_export)

    def showEvent(self, event):
        super().showEvent(event)
        QApplication.instance().installEventFilter(self)

    def hideEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        super().hideEvent(event)

    def set_items(self, items: Iterable[ReportHistoryDisplayItem]) -> None:
        self._items = tuple(sorted(items, key=saved_report_order, reverse=True))
        self._render()

    def set_report_type(self, report_type):
        caption = {"daily": _("Daily"), "weekly": _("Weekly"), "monthly": _("Monthly")}[report_type]
        self.scope_label.setText(_("{type} | This account | Newest saved first").format(type=caption))
        self.scope_label.setToolTip(_("Saved reports for this account, not revisions of the open report."))

    def set_selected_report(self, report_id: int | None) -> None:
        self._selected_report_id = report_id
        for button in self._buttons.values():
            selected = report_id is not None and button.property("report_id") == report_id
            button.set_current(selected)

    def _render(self) -> None:
        self._hovered_button = None
        while self.scroll_layout.count():
            item = self.scroll_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # Keep ownership until deletion so queued show events cannot create windows.
                widget.hide()
                widget.deleteLater()
        self._buttons = {}

        query = self.search_line_edit.text().strip().lower()
        visible = [
            item
            for item in self._items
            if not query or query in _history_label(item).lower()
        ]
        if not visible:
            label = QLabel(_("No saved reports"), self.scroll_widget)
            label.setObjectName("empty_report_history_label")
            label.setProperty("role", "secondary")
            self.scroll_layout.addWidget(label)
            self.scroll_layout.addStretch(1)
            return

        current_month = ""
        for index, item in enumerate(visible):
            stamp = item.created_at
            if stamp is not None:
                stamp = stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp
                month = month_label(stamp.astimezone().date())
            else:
                month = _("Save time unavailable")
            if month != current_month:
                current_month = month
                heading = QLabel(month, self.scroll_widget)
                heading.setObjectName("report_history_month_label")
                self.scroll_layout.addWidget(heading)
            button = ReportHistoryButton(item, self.scroll_widget, allow_delete=self._allow_delete)
            button.setObjectName("report_history_item_button")
            button.setProperty("nav_item", True)
            button.setProperty("report_id", item.report_id)
            button.set_current(item.report_id is not None and item.report_id == self._selected_report_id)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setMinimumHeight(button.heightForWidth(self.scroll_area.viewport().width()))
            button.clicked.connect(lambda _checked=False, selected=item: self.item_selected.emit(selected))
            button.delete_requested.connect(lambda selected=item: self.delete_requested.emit(selected))
            button.hovered.connect(self._track_hover)
            self._buttons[index] = button
            self.scroll_layout.addWidget(button)
        self.scroll_layout.addStretch(1)

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
