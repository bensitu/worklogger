"""Date button with a localized, keyboard-accessible calendar popup."""

from datetime import date

from PySide6.QtCore import QDate, QEvent, QLocale, QPoint, Qt, Signal
from PySide6.QtGui import QKeySequence, QPalette, QShortcut, QTextCharFormat
from PySide6.QtWidgets import QCalendarWidget, QFrame, QPushButton, QToolButton, QVBoxLayout

from worklogger.infrastructure.i18n import _, get_language
from worklogger.presentation.date_labels import day_label
from worklogger.presentation.widgets.icons import set_button_icon


class MonthCalendar(QCalendarWidget):
    def paintCell(self, painter, rect, day):
        painter.save()
        if (day.year(), day.month()) != (self.yearShown(), self.monthShown()) and day != self.selectedDate():
            painter.setOpacity(painter.opacity() * 0.45)
        super().paintCell(painter, rect, day)
        painter.restore()


class DatePickerButton(QPushButton):
    date_selected = Signal(object)

    def __init__(self, parent=None, *, week_start_monday=False):
        super().__init__(parent)
        self.setObjectName("date_picker_button")
        self.setProperty("variant", "outline")
        self.setAutoDefault(False)
        self.setToolTip(_("Calendar"))
        self.setAccessibleName(_("Date"))
        self._day = date.today()
        self._week_start_monday = week_start_monday
        self._popup = None
        self.calendar = None
        self.clicked.connect(self.open_calendar)

    def set_date(self, day):
        self._day = day
        self.setText(day_label(day))

    def set_week_start_monday(self, enabled):
        self._week_start_monday = enabled

    def open_calendar(self):
        if not self.isEnabled():
            return
        if self._popup is None:
            self._popup = QFrame(self, Qt.WindowType.Popup)
            self._popup.setObjectName("date_picker_popup_frame")
            layout = QVBoxLayout(self._popup)
            layout.setContentsMargins(8, 8, 8, 8)
            self.calendar = MonthCalendar(self._popup)
            self.calendar.setObjectName("date_picker_calendar_widget")
            self.calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
            self.calendar.setMinimumDate(QDate(1, 1, 1))
            self.calendar.setMaximumDate(QDate(9999, 12, 31))
            self.calendar.clicked.connect(self._choose_date)
            self.calendar.activated.connect(self._choose_date)
            for name, icon, caption in (("qt_calendar_prevmonth", "chevron-left", _("Previous month")),
                                        ("qt_calendar_nextmonth", "chevron-right", _("Next month"))):
                button = self.calendar.findChild(QToolButton, name)
                if button is not None:
                    set_button_icon(button, icon)
                    button.setToolTip(caption)
                    button.setAccessibleName(caption)
            layout.addWidget(self.calendar)
            shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self._popup)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(self._popup.hide)
        self.calendar.setLocale(QLocale(get_language()))
        self.calendar.setFirstDayOfWeek(Qt.DayOfWeek.Monday if self._week_start_monday else Qt.DayOfWeek.Sunday)
        weekend = QTextCharFormat()
        weekend.setForeground(self.palette().color(QPalette.ColorRole.Link))
        for day in (Qt.DayOfWeek.Saturday, Qt.DayOfWeek.Sunday):
            self.calendar.setWeekdayTextFormat(day, weekend)
        self.calendar.setSelectedDate(QDate(self._day.year, self._day.month, self._day.day))
        self.calendar.setCurrentPage(self._day.year, self._day.month)
        self._popup.adjustSize()
        bounds = self.screen().availableGeometry()
        anchor = self.mapToGlobal(QPoint(self.width() // 2, self.height()))
        x = max(bounds.left(), min(anchor.x() - self._popup.width() // 2, bounds.right() - self._popup.width() + 1))
        y = anchor.y() + 4
        if y + self._popup.height() > bounds.bottom() + 1:
            y = anchor.y() - self.height() - self._popup.height() - 4
        self._popup.move(x, max(bounds.top(), y))
        self._popup.show()
        self.calendar.setFocus(Qt.FocusReason.PopupFocusReason)

    def _choose_date(self, chosen):
        if not self.isEnabled() or not self._popup.isVisible() or not chosen.isValid():
            return
        self._popup.hide()
        self.date_selected.emit(chosen.toPython())

    def hideEvent(self, event):
        if self._popup is not None:
            self._popup.hide()
        super().hideEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.EnabledChange and not self.isEnabled() and getattr(self, "_popup", None) is not None:
            self._popup.hide()
