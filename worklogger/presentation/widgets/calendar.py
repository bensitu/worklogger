"""Calendar Qt widgets bound to calendar ViewModel state."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from worklogger.infrastructure.i18n import _
from worklogger.presentation.viewmodels.calendar import (
    CalendarDayCell,
    CalendarMonthViewState,
    event_count_label,
)


class CalendarDayButton(QPushButton):
    """A calendar cell button with lightweight painted markers."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cell: CalendarDayCell | None = None
        self.setObjectName("calendar_day_button")
        self.setMinimumHeight(86)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    @property
    def cell(self) -> CalendarDayCell | None:
        return self._cell

    def set_cell(self, cell: CalendarDayCell) -> None:
        self._cell = cell
        self.setText("\n".join(cell.text_lines))
        self.setToolTip(_tooltip_for_cell(cell))
        self.setStyleSheet(_calendar_cell_qss(cell))
        self.setProperty("day", cell.day.isoformat())
        self.setProperty("in_month", cell.in_month)
        self.setProperty("style_key", cell.style.key)
        self.update()

    def paintEvent(self, event: object) -> None:
        super().paintEvent(event)
        cell = self._cell
        if cell is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if cell.work_type_marker_color:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(cell.work_type_marker_color))
            painter.drawRoundedRect(QRectF(4, 4, 5, 24), 3, 3)

        if cell.has_note_marker:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(cell.style.hover_border))
            note_x = 15 if cell.work_type_marker_color else 7
            painter.drawEllipse(note_x, 7, 7, 7)

        if cell.show_overnight_marker:
            painter.setPen(QPen(QColor(cell.style.foreground), 1))
            painter.drawText(
                QRectF(self.width() - 22, 5, 16, 14),
                Qt.AlignmentFlag.AlignCenter,
                "N",
            )

        if cell.event_count > 0:
            badge = QRectF(self.width() - 24, self.height() - 20, 18, 14)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(cell.style.hover_border))
            painter.drawRoundedRect(badge, 6, 6)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(
                badge,
                Qt.AlignmentFlag.AlignCenter,
                str(min(cell.event_count, 9)),
            )
        painter.end()


class CalendarView(QWidget):
    day_selected = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state: CalendarMonthViewState | None = None
        self._buttons: list[CalendarDayButton] = []
        self._week_total_labels: list[QLabel] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.month_title = QLabel("")
        self.month_title.setObjectName("month_title")
        self.month_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.month_title)

        self.grid_frame = QFrame()
        self.grid_frame.setObjectName("calendar_grid_frame")
        self.grid = QGridLayout(self.grid_frame)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(6)
        self.grid.setVerticalSpacing(6)
        layout.addWidget(self.grid_frame)

    @property
    def state(self) -> CalendarMonthViewState | None:
        return self._state

    def day_buttons(self) -> tuple[CalendarDayButton, ...]:
        return tuple(self._buttons)

    def week_total_labels(self) -> tuple[QLabel, ...]:
        return tuple(self._week_total_labels)

    def set_state(self, state: CalendarMonthViewState) -> None:
        self._state = state
        self.month_title.setText(f"{state.year}/{state.month:02d}")
        _clear_layout(self.grid)
        self._buttons = []
        self._week_total_labels = []

        for column, header in enumerate(state.week_headers):
            label = QLabel(header)
            label.setObjectName("week_header_label")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.grid.addWidget(label, 0, column)
        total_header = QLabel(_("Total"))
        total_header.setObjectName("week_header_label")
        total_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.grid.addWidget(total_header, 0, 7)

        for index, cell in enumerate(state.cells):
            row = index // 7 + 1
            column = index % 7
            button = CalendarDayButton()
            button.set_cell(cell)
            button.clicked.connect(lambda _checked=False, day=cell.day: self.day_selected.emit(day))
            self.grid.addWidget(button, row, column)
            self._buttons.append(button)

        for week_index, total in enumerate(state.weekly_totals):
            label = QLabel(f"{total:.1f}{_('h')}" if total > 0 else "")
            label.setObjectName("week_total_label")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.grid.addWidget(label, week_index + 1, 7)
            self._week_total_labels.append(label)


def _calendar_cell_qss(cell: CalendarDayCell) -> str:
    border_width = cell.style.border_width
    if not cell.in_month:
        foreground = "#8a8f9c"
    else:
        foreground = cell.style.foreground
    return (
        "QPushButton#calendar_day_button{"
        f"background-color:{cell.style.background};"
        f"color:{foreground};"
        f"border:{border_width}px solid {cell.style.border};"
        "border-radius:6px;"
        "font-size:11px;"
        "text-align:center;"
        "padding:2px;"
        "}"
        "QPushButton#calendar_day_button:hover{"
        f"border:2px solid {cell.style.hover_border};"
        "}"
    )


def _tooltip_for_cell(cell: CalendarDayCell) -> str:
    details: list[str] = []
    if cell.note_tooltip:
        details.append(cell.note_tooltip)
    if cell.event_count:
        details.append(event_count_label(cell.event_count))
    return "\n".join(details)


def _clear_layout(layout: QGridLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
