"""Shared week, month, year, custom, and unrestricted date-range controls."""

from datetime import date

from PySide6.QtCore import QDate, QLocale, QSignalBlocker, Signal
from PySide6.QtWidgets import (QComboBox, QDateEdit, QGridLayout, QHBoxLayout,
    QLabel, QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from worklogger.infrastructure.i18n import _, get_language
from worklogger.presentation.widgets.date_picker import DatePickerButton, configure_calendar_popup
from worklogger.presentation.widgets.icons import set_button_icon


class DateRangeControls(QWidget):
    range_changed = Signal()

    def __init__(self, day: date, parent=None, *, horizontal=False, week_start_monday=False):
        super().__init__(parent)
        self._period = day.replace(day=1)
        self.week_start_monday = week_start_monday
        root = QGridLayout(self) if horizontal else QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10 if horizontal else 8)
        self.mode_input = QComboBox()
        for label, value in ((_("Month"), "month"), (_("Year"), "year"),
                             (_("Custom range"), "custom"), (_("All dates"), "all")):
            self.mode_input.addItem(label, value)
        self.mode_input.setAccessibleName(_("Date range"))
        if horizontal:
            for column in range(3):
                root.setColumnStretch(column, 1)
            root.addWidget(self.mode_input, 0, 0)
        else:
            root.addWidget(self.mode_input)
        self.period_widget = QWidget()
        period = QHBoxLayout(self.period_widget)
        period.setContentsMargins(0, 0, 0, 0)
        period.setSpacing(4)
        self.previous_button, self.next_button = QToolButton(), QToolButton()
        for button, icon, caption in ((self.previous_button, "chevron-left", _("Previous period")),
                                     (self.next_button, "chevron-right", _("Next period"))):
            button.setProperty("variant", "outline")
            button.setToolTip(caption)
            button.setAccessibleName(caption)
            set_button_icon(button, icon)
        self.period_button = DatePickerButton()
        for button in (self.previous_button, self.period_button, self.next_button):
            button.setSizePolicy(button.sizePolicy().horizontalPolicy(), QSizePolicy.Policy.Minimum)
        period.addWidget(self.previous_button)
        period.addWidget(self.period_button, 1)
        period.addWidget(self.next_button)
        if horizontal:
            root.addWidget(self.period_widget, 0, 1, 1, 2)
        else:
            root.addWidget(self.period_widget)
        self.range_widget = QWidget()
        dates = QGridLayout(self.range_widget)
        dates.setContentsMargins(0, 0, 0, 0)
        dates.setSpacing(4)
        dates.setColumnStretch(1, 1)
        self.start_input, self.end_input = QDateEdit(), QDateEdit()
        for row, (field, caption, value) in enumerate(((self.start_input, _("From"), self._period),
                                                     (self.end_input, _("To"), day))):
            field.setDateRange(QDate(1, 1, 1), QDate(9999, 12, 31))
            field.setDisplayFormat("yyyy-MM-dd")
            configure_calendar_popup(field)
            field.setDate(value)
            field.setAccessibleName(caption)
            label = QLabel(caption)
            label.setBuddy(field)
            dates.addWidget(label, 0 if horizontal else row, row * 2 if horizontal else 0)
            dates.addWidget(field, 0 if horizontal else row, row * 2 + 1 if horizontal else 1)
        if horizontal:
            dates.setColumnStretch(3, 1)
        if horizontal:
            root.addWidget(self.range_widget, 0, 1, 1, 2)
        else:
            root.addWidget(self.range_widget)
        self.mode_input.currentIndexChanged.connect(self._changed)
        self.period_button.date_selected.connect(self.select_period)
        self.previous_button.clicked.connect(lambda: self._move(-1))
        self.next_button.clicked.connect(lambda: self._move(1))
        self.start_input.dateChanged.connect(self._changed)
        self.end_input.dateChanged.connect(self._changed)
        self.sync_controls()

    def bounds(self) -> tuple[date, date]:
        mode = self.mode_input.currentData()
        if mode == "all":
            return date.min, date.max
        if mode == "custom":
            return self.start_input.date().toPython(), self.end_input.date().toPython()
        if mode == "year":
            return date(self._period.year, 1, 1), date(self._period.year, 12, 31)
        if mode == "week":
            offset = (self._period.weekday() + int(not self.week_start_monday)) % 7
            first = max(date.min.toordinal(), self._period.toordinal() - offset)
            last = min(date.max.toordinal(), self._period.toordinal() - offset + 6)
            return date.fromordinal(first), date.fromordinal(last)
        first = QDate(self._period.replace(day=1))
        return first.toPython(), first.addDays(first.daysInMonth() - 1).toPython()

    def set_modes(self, modes, *, default, day):
        labels = {"week": _("Week"), "month": _("Month"), "year": _("Year"),
                  "custom": _("Custom range"), "all": _("All dates")}
        if not modes or default not in modes or any(mode not in labels for mode in modes):
            raise ValueError("date_range_mode_invalid")
        with QSignalBlocker(self.mode_input), QSignalBlocker(self.start_input), QSignalBlocker(self.end_input):
            self.mode_input.clear()
            for mode in modes:
                self.mode_input.addItem(labels[mode], mode)
            self.mode_input.setCurrentIndex(self.mode_input.findData(default))
            self._period = day
            self.start_input.setDate(day.replace(day=1))
            self.end_input.setDate(day)
        self.sync_controls()

    def set_custom_range(self, start: date, end: date):
        with QSignalBlocker(self.mode_input), QSignalBlocker(self.start_input), QSignalBlocker(self.end_input):
            self.mode_input.setCurrentIndex(self.mode_input.findData("custom"))
            self.start_input.setDate(start)
            self.end_input.setDate(end)
        self._changed()

    def select_period(self, day: date):
        self._period = day if self.mode_input.currentData() == "week" else day.replace(day=1)
        self._changed()

    def _move(self, direction: int):
        current = QDate(self._period)
        mode = self.mode_input.currentData()
        target = (current.addYears(direction) if mode == "year" else current.addDays(direction * 7)
                  if mode == "week" else current.addMonths(direction))
        if target.isValid() and 1 <= target.year() <= 9999:
            self.select_period(target.toPython())

    def _changed(self, *_args):
        self.sync_controls()
        self.range_changed.emit()

    def sync_controls(self):
        mode = self.mode_input.currentData()
        self.period_widget.setVisible(mode in ("week", "month", "year"))
        self.range_widget.setVisible(mode == "custom")
        self.period_button.set_week_start_monday(self.week_start_monday)
        self.period_button.set_date(self._period)
        self.period_button.setText(QLocale(get_language()).toString(QDate(self._period), "yyyy" if mode == "year" else "yyyy-MM"))
        self.period_button.setToolTip(_("Calendar"))
        if mode == "week":
            start, end = self.bounds()
            self.period_button.setText(f"{start.isoformat()}\n{end.isoformat()}")
            self.period_button.setToolTip(f"{start.isoformat()} - {end.isoformat()}")
        self.previous_button.setEnabled(self._period.year > 1 if mode == "year" else self._period.replace(day=1) > date.min)
        self.next_button.setEnabled(self._period.year < 9999 if mode == "year" else self._period.replace(day=1) < date(9999, 12, 1))
        if mode == "week":
            self.previous_button.setEnabled(self.bounds()[0] > date.min)
            self.next_button.setEnabled(self.bounds()[1] < date.max)
