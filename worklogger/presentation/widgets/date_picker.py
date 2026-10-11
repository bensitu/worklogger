"""Date button with a localized, keyboard-accessible calendar popup."""

from datetime import date
from html import escape

from PySide6.QtCore import QDate, QEvent, QLocale, QPoint, QRect, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QKeySequence, QPainter, QShortcut, QTextCharFormat
from PySide6.QtWidgets import QCalendarWidget, QFrame, QPushButton, QSizePolicy, QSpinBox, QTableView, QToolButton, QToolTip, QVBoxLayout

from worklogger.infrastructure.i18n import _, get_language
from worklogger.presentation.date_labels import day_label
from worklogger.presentation.theme import ThemeEngine
from worklogger.presentation.theme.context import current_colors
from worklogger.presentation.widgets.icons import set_button_icon
from worklogger.presentation.widgets._style import apply_numeric_input_padding
from worklogger.presentation.widgets.status_label import StatusLabel


class MonthCalendar(QCalendarWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._colors = current_colors()
        self._follow_application_theme = True
        self._holidays = {}
        self._cell_rects = {}
        self._appearance_timer = QTimer(self)
        self._appearance_timer.setSingleShot(True)
        self._appearance_timer.timeout.connect(self._sync_appearance)
        self.setObjectName("date_picker_calendar_widget")
        self.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.setLocale(QLocale(get_language()))
        year_editor = self.findChild(QSpinBox, "qt_calendar_yearedit")
        if year_editor is not None:
            apply_numeric_input_padding(year_editor)
        for name, icon, caption in (("qt_calendar_prevmonth", "chevron-left", _("Previous month")),
                                    ("qt_calendar_nextmonth", "chevron-right", _("Next month"))):
            button = self.findChild(QToolButton, name)
            if button is not None:
                set_button_icon(button, icon)
                button.setToolTip(caption)
                button.setAccessibleName(caption)
        self.findChild(QTableView).viewport().installEventFilter(self)
        self.currentPageChanged.connect(lambda *_args: self._cell_rects.clear())
        self._sync_appearance()

    def set_colors(self, colors):
        self._follow_application_theme = False
        self._colors = colors
        self._sync_appearance()

    @Slot()
    def _sync_appearance(self):
        if self._follow_application_theme:
            self._colors = current_colors()
        weekend = QTextCharFormat()
        weekend.setForeground(QColor(self._colors.accent))
        for day in (Qt.DayOfWeek.Saturday, Qt.DayOfWeek.Sunday):
            self.setWeekdayTextFormat(day, weekend)
        self.updateCells()

    def showEvent(self, event):
        self.setLocale(QLocale(get_language()))
        self._sync_appearance()
        super().showEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if (event.type() in (QEvent.Type.PaletteChange, QEvent.Type.StyleChange)
                and hasattr(self, "_appearance_timer")):
            self._appearance_timer.start(0)

    def set_holidays(self, holidays):
        self._holidays = dict(holidays)
        self.updateCells()

    def visible_range(self):
        first = QDate(self.yearShown(), self.monthShown(), 1)
        offset = (first.dayOfWeek() - self.firstDayOfWeek().value) % 7 or 7
        start = max(first.addDays(-offset), self.minimumDate())
        end = min(first.addDays(41 - offset), self.maximumDate())
        return start.toPython(), end.toPython()

    def paintCell(self, painter, rect, day):
        value = day.toPython() if day.isValid() and 1 <= day.year() <= 9999 else None
        if value is not None:
            self._cell_rects[value] = QRect(rect)
        selected = day == self.selectedDate()
        holiday = value in self._holidays
        colors = self._colors
        painter.save()
        painter.fillRect(rect, QColor(colors.accent if selected else colors.surface))
        if (day < self.minimumDate() or day > self.maximumDate()
                or (day.year(), day.month()) != (self.yearShown(), self.monthShown())) and not selected:
            painter.setOpacity(painter.opacity() * 0.45)
        foreground = (colors.highlighted_text if selected else colors.danger if holiday
                      else colors.accent if day.dayOfWeek() >= 6 else colors.text)
        painter.setPen(QColor(foreground))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.locale().toString(day.day()))
        if holiday:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(foreground))
            painter.drawEllipse(QPoint(rect.center().x(), rect.bottom() - 2), 2, 2)
        painter.restore()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.ToolTip:
            name = next((self._holidays.get(day, "") for day, rect in self._cell_rects.items()
                         if rect.contains(event.pos())), "")
            if name:
                QToolTip.showText(event.globalPos(), "<qt>" + escape(name) + "</qt>", watched)
            else:
                QToolTip.hideText()
            return True
        return super().eventFilter(watched, event)


def configure_calendar_popup(field):
    field.setCalendarPopup(True)
    first_day = field.calendarWidget().firstDayOfWeek()
    calendar = MonthCalendar(field)
    calendar.setFirstDayOfWeek(first_day)
    field.setCalendarWidget(calendar)
    popup = calendar.parentWidget()
    popup.setObjectName("date_picker_popup_frame")
    popup.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
    popup.layout().setContentsMargins(8, 8, 8, 8)
    return calendar


class DatePickerButton(QPushButton):
    date_selected = Signal(object)
    range_requested = Signal(object, object)

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
        self._colors = ThemeEngine().palette()
        self.calendar = None
        self.clicked.connect(self.open_calendar)

    def set_date(self, day):
        self._day = day
        self.setText(day_label(day))

    def set_week_start_monday(self, enabled):
        self._week_start_monday = enabled

    def set_colors(self, colors):
        self._colors = colors
        if self.calendar is not None:
            self.calendar.set_colors(colors)

    def set_holidays(self, holidays):
        if self.calendar is not None:
            self.calendar.set_holidays(holidays)
            self.holiday_status_label.clear()
            self._resize_popup()

    def set_holiday_error(self, message):
        self.holiday_status_label.setText(message)
        self._resize_popup()

    def _resize_popup(self):
        if self._popup.isVisible():
            self._popup.adjustSize()
            self._position_popup()

    def request_holidays(self):
        if self.calendar is not None and self._popup.isVisible():
            self.range_requested.emit(*self.calendar.visible_range())

    def open_calendar(self):
        if not self.isEnabled():
            return
        if self._popup is None:
            self._popup = QFrame(self, Qt.WindowType.Popup)
            self._popup.setObjectName("date_picker_popup_frame")
            layout = QVBoxLayout(self._popup)
            layout.setContentsMargins(8, 8, 8, 8)
            self.calendar = MonthCalendar(self._popup)
            self.calendar.setMinimumDate(QDate(1, 1, 1))
            self.calendar.setMaximumDate(QDate(9999, 12, 31))
            self.calendar.set_colors(self._colors)
            self.calendar.currentPageChanged.connect(self.request_holidays)
            self.calendar.clicked.connect(self._choose_date)
            self.calendar.activated.connect(self._choose_date)
            layout.addWidget(self.calendar)
            self.holiday_status_label = StatusLabel()
            self.holiday_status_label.setObjectName("date_picker_holiday_status_label")
            self.holiday_status_label.setTextFormat(Qt.TextFormat.PlainText)
            self.holiday_status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            layout.addWidget(self.holiday_status_label)
            shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self._popup)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(self._popup.hide)
        self.calendar.setLocale(QLocale(get_language()))
        self.calendar.setFirstDayOfWeek(Qt.DayOfWeek.Monday if self._week_start_monday else Qt.DayOfWeek.Sunday)
        self.calendar.setSelectedDate(QDate(self._day.year, self._day.month, self._day.day))
        self.calendar.setCurrentPage(self._day.year, self._day.month)
        self._popup.adjustSize()
        self._position_popup()
        self._popup.show()
        self.calendar.setFocus(Qt.FocusReason.PopupFocusReason)
        self.request_holidays()

    def _position_popup(self):
        bounds = self.screen().availableGeometry()
        anchor = self.mapToGlobal(QPoint(self.width() // 2, self.height()))
        x = max(bounds.left(), min(anchor.x() - self._popup.width() // 2, bounds.right() - self._popup.width() + 1))
        y = anchor.y() + 4
        if y + self._popup.height() > bounds.bottom() + 1:
            y = anchor.y() - self.height() - self._popup.height() - 4
        self._popup.move(x, max(bounds.top(), y))

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
