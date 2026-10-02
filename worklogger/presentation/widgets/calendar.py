"""Calendar Qt widgets bound to calendar ViewModel state."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen
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
from worklogger.presentation.widgets.icons import ui_icon
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
        self.setMinimumHeight(72)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    @property
    def cell(self) -> CalendarDayCell | None:
        return self._cell

    def set_cell(self, cell: CalendarDayCell) -> None:
        self._cell = cell
        self.setText("\n".join(cell.text_lines))
        self.setToolTip(_tooltip_for_cell(cell))
        self.setProperty("day", cell.day.isoformat())
        self.setProperty("in_month", cell.in_month)
        self.setProperty("style_key", cell.style.key)
        self.update()

    def enterEvent(self, event: object) -> None:
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: object) -> None:
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event: object) -> None:
        cell = self._cell
        if cell is None:
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        border_color = cell.style.hover_border if self.underMouse() else cell.style.border
        border_width = 2 if self.underMouse() else cell.style.border_width
        foreground = cell.style.foreground if cell.in_month else "#8a8f9c"
        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)
        painter.setPen(QPen(QColor(border_color), border_width))
        painter.setBrush(QColor(cell.style.background))
        painter.drawRoundedRect(rect, 6, 6)

        lines = list(cell.text_lines)
        font = painter.font()
        font.setPixelSize(12)
        font.setBold(cell.is_selected)
        painter.setFont(font)
        painter.setPen(QColor(foreground))
        if lines:
            day_font = painter.font()
            day_font.setPixelSize(14)
            painter.setFont(day_font)
            painter.drawText(
                QRectF(10, 8, self.width() - (30 if cell.event_count else 20), 18),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                lines[0],
            )
        if cell.holiday_name:
            holiday_font = painter.font()
            holiday_font.setPixelSize(9)
            painter.setFont(holiday_font)
            painter.setPen(QColor("#ef4444" if not cell.is_selected else "#ffffff"))
            holiday_width = self.width() - (32 if cell.event_count else 20)
            painter.drawText(
                QRectF(10, 24, holiday_width, 14),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                painter.fontMetrics().elidedText(cell.holiday_name, Qt.TextElideMode.ElideRight, int(holiday_width)),
            )
        painter.setFont(font)
        painter.setPen(QColor(foreground))
        metric_lines = lines[-2:] if len(lines) >= 2 else ()
        metric_top = max(38 if cell.holiday_name else 28, self.height() - 34)
        for index, line in enumerate(metric_lines):
            metric_width = self.width() - 16
            painter.drawText(
                QRectF(8, metric_top + index * 14, metric_width, 14),
                Qt.AlignmentFlag.AlignCenter,
                line,
            )

        if cell.work_type_marker_color:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(cell.work_type_marker_color))
            painter.drawRoundedRect(QRectF(2, 4, 3, self.height() - 8), 1.5, 1.5)

        if cell.has_note_marker:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(cell.style.hover_border))
            painter.drawEllipse(self.width() - 8, 2, 5, 5)

        if cell.show_overnight_marker:
            icon = ui_icon("moon", primary=cell.is_selected)
            icon.paint(painter, QRect(self.width() - 22, 8, 14, 14), Qt.AlignmentFlag.AlignCenter, QIcon.Mode.Normal)

        if cell.event_count > 0:
            badge = QRectF(self.width() - 22, 25 if cell.show_overnight_marker else 8, 18, 14)
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
        self._month_only = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.month_title = QLabel("")
        self.month_title.setObjectName("month_title_label")
        self.month_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.month_title)

        self.grid_frame = QFrame()
        self.grid_frame.setObjectName("calendar_grid_frame")
        self.grid = QGridLayout(self.grid_frame)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(6)
        self.grid.setVerticalSpacing(6)
        layout.addWidget(self.grid_frame, 1)

    def set_month_only(self, enabled: bool) -> None:
        self._month_only = enabled
        if self._state is not None:
            self.set_state(self._state)

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
        visible_weeks = max(index // 7 + 1 for index, cell in enumerate(state.cells) if cell.in_month)
        for column in range(8):
            self.grid.setColumnStretch(column, 1 if column < 7 else 0)
        for row in range(1, 7):
            self.grid.setRowStretch(row, 1 if not self._month_only or row <= visible_weeks else 0)

        for column, header in enumerate(state.week_headers):
            label = QLabel(header)
            label.setObjectName("week_header_label")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setProperty("weekend", header in (_("Sat"), _("Sun")))
            self.grid.addWidget(label, 0, column)
        total_header = QLabel(_("Total"))
        total_header.setObjectName("week_header_label")
        total_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.grid.addWidget(total_header, 0, 7)
        total_header.setVisible(not self._month_only)

        for index, cell in enumerate(state.cells):
            row = index // 7 + 1
            column = index % 7
            button = CalendarDayButton()
            button.set_cell(cell)
            button.clicked.connect(lambda _checked=False, day=cell.day: self.day_selected.emit(day))
            self.grid.addWidget(button, row, column)
            button.setVisible(not self._month_only or cell.in_month)
            self._buttons.append(button)

        for week_index, total in enumerate(state.weekly_totals):
            label = QLabel(f"{total:.1f}{_('h')}" if total > 0 else "")
            label.setObjectName("week_total_label")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.grid.addWidget(label, week_index + 1, 7)
            label.setVisible(not self._month_only)
            self._week_total_labels.append(label)


def _tooltip_for_cell(cell: CalendarDayCell) -> str:
    details: list[str] = []
    if cell.holiday_name:
        details.append(cell.holiday_name)
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
