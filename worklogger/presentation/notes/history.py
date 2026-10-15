"""Date-filtered note previews with asynchronous, cursor-based pagination."""

from dataclasses import replace
from datetime import date

from PySide6.QtCore import QDate, QLocale, QSignalBlocker, QTimer, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QToolButton,
    QVBoxLayout, QWidget)

from worklogger.domain.notes.models import NoteHistoryFilter
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import _, get_language
from worklogger.presentation.job_runner import owned_callback
from worklogger.presentation.theme.context import current_colors
from worklogger.presentation.widgets.date_picker import DatePickerButton, configure_calendar_popup
from worklogger.presentation.widgets.icons import set_button_icon
from worklogger.presentation.widgets.two_line_delegate import TwoLineItemDelegate


class NoteHistoryBrowser(QWidget):
    error_occurred = Signal(object)

    def __init__(self, view_model, day: date, *, job_runner, parent=None):
        super().__init__(parent)
        self._view_model, self._runner = view_model, job_runner
        self._period = day.replace(day=1)
        self._active_day = day
        self._revision = 0
        self._busy = False
        self._closed = False
        self._next_before = None
        self._loaded_filter = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(350)
        self._timer.timeout.connect(self._load)
        self.setMinimumWidth(220)
        self.setMaximumWidth(270)
        self._build_ui(day)
        self._sync_controls()

    def _build_ui(self, day):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.mode_input = QComboBox()
        for label, mode in ((_("Month"), "month"), (_("Year"), "year"),
                            (_("Custom range"), "custom"), (_("All dates"), "all")):
            self.mode_input.addItem(label, mode)
        self.mode_input.setAccessibleName(_("Date range"))
        layout.addWidget(self.mode_input)
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
        self.period_button.set_colors(current_colors())
        period.addWidget(self.previous_button)
        period.addWidget(self.period_button, 1)
        period.addWidget(self.next_button)
        layout.addWidget(self.period_widget)
        self.range_widget = QWidget()
        dates = QVBoxLayout(self.range_widget)
        dates.setContentsMargins(0, 0, 0, 0)
        dates.setSpacing(4)
        self.start_input, self.end_input = QDateEdit(), QDateEdit()
        for field, caption, value in ((self.start_input, _("From"), self._period),
                                      (self.end_input, _("To"), day)):
            field.setDateRange(QDate(1, 1, 1), QDate(9999, 12, 31))
            field.setDisplayFormat("yyyy-MM-dd")
            configure_calendar_popup(field)
            field.setDate(value)
            field.setAccessibleName(caption)
            label = QLabel(caption)
            label.setBuddy(field)
            row = QHBoxLayout()
            row.addWidget(label)
            row.addWidget(field, 1)
            dates.addLayout(row)
        layout.addWidget(self.range_widget)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(_("Search notes"))
        self.search_input.setAccessibleName(_("Search notes"))
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMaxLength(256)
        layout.addWidget(self.search_input)
        self.all_dates_checkbox = QCheckBox(_("Search all dates"))
        layout.addWidget(self.all_dates_checkbox)
        self.range_label = QLabel()
        self.count_label = QLabel()
        self.empty_label = QLabel(_("No notes found"))
        for label in (self.range_label, self.count_label, self.empty_label):
            label.setProperty("role", "secondary")
            label.setWordWrap(True)
            layout.addWidget(label)
        self.empty_label.hide()
        self.history_list = QListWidget()
        self.history_list.setObjectName("note_history_list_widget")
        self.history_list.setAccessibleName(_("Notes"))
        self.history_list.setItemDelegate(TwoLineItemDelegate(self.history_list))
        self.history_list.setSpacing(4)
        self.history_list.setFrameShape(QFrame.Shape.NoFrame)
        self.history_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.history_list, 1)
        self.more_button = QPushButton(_("Load more"))
        set_button_icon(self.more_button, "chevron-down")
        self.more_button.hide()
        layout.addWidget(self.more_button)
        self.mode_input.currentIndexChanged.connect(self._filters_changed)
        self.period_button.date_selected.connect(self._select_period)
        self.previous_button.clicked.connect(lambda: self._move_period(-1))
        self.next_button.clicked.connect(lambda: self._move_period(1))
        self.start_input.dateChanged.connect(self._filters_changed)
        self.end_input.dateChanged.connect(self._filters_changed)
        self.search_input.textChanged.connect(self._filters_changed)
        self.all_dates_checkbox.toggled.connect(self._filters_changed)
        self.more_button.clicked.connect(lambda: self._load(append=True))

    def _sync_controls(self):
        mode = self.mode_input.currentData()
        has_query = bool(self.search_input.text().strip())
        if not has_query:
            with QSignalBlocker(self.all_dates_checkbox):
                self.all_dates_checkbox.setChecked(False)
        global_search = has_query and self.all_dates_checkbox.isChecked()
        self.all_dates_checkbox.setEnabled(has_query and mode != "all")
        self.mode_input.setEnabled(not global_search)
        self.period_widget.setVisible(mode in ("month", "year"))
        self.range_widget.setVisible(mode == "custom")
        self.period_widget.setEnabled(not global_search)
        self.range_widget.setEnabled(not global_search)
        self.period_button.set_date(self._period)
        pattern = "yyyy" if mode == "year" else "yyyy-MM"
        self.period_button.setText(QLocale(get_language()).toString(QDate(self._period), pattern))
        self.previous_button.setEnabled(self._period.year > 1 if mode == "year" else self._period > date.min)
        self.next_button.setEnabled(self._period.year < 9999 if mode == "year"
                                    else self._period < date(9999, 12, 1))
        filters = self._filters()
        self.range_label.setText(_("Invalid date range") if filters is None else _("All dates")
                                 if (filters.start, filters.end) == (date.min, date.max)
                                 else f"{filters.start.isoformat()} - {filters.end.isoformat()}")

    def _filters(self):
        text = self.search_input.text().strip()
        mode = self.mode_input.currentData()
        if mode == "all" or (text and self.all_dates_checkbox.isChecked()):
            start, end = date.min, date.max
        elif mode == "custom":
            start, end = self.start_input.date().toPython(), self.end_input.date().toPython()
        elif mode == "year":
            start, end = date(self._period.year, 1, 1), date(self._period.year, 12, 31)
        else:
            first = QDate(self._period)
            start, end = self._period, first.addDays(first.daysInMonth() - 1).toPython()
        return NoteHistoryFilter(start, end, text) if start <= end else None

    def _select_period(self, day):
        self._period = day.replace(day=1)
        self._filters_changed()

    def _move_period(self, direction):
        current = QDate(self._period)
        target = current.addYears(direction) if self.mode_input.currentData() == "year" else current.addMonths(direction)
        if target.isValid() and 1 <= target.year() <= 9999:
            self._select_period(target.toPython())

    def _filters_changed(self, *_args):
        self._revision += 1
        self._next_before = None
        self.more_button.hide()
        self._sync_controls()
        self._timer.start()

    def refresh(self):
        self._revision += 1
        self._load()

    def stop(self, *_args):
        self._closed = True
        self._timer.stop()

    def set_active_day(self, day):
        self._active_day = day
        with QSignalBlocker(self.history_list):
            self.history_list.setCurrentRow(-1)
            for row in range(self.history_list.count()):
                item = self.history_list.item(row)
                if item.data(Qt.ItemDataRole.UserRole) == day:
                    self.history_list.setCurrentItem(item)
                    break

    def _load(self, *, append=False):
        if self._closed:
            return
        self._timer.stop()
        if self._busy:
            self._timer.start()
            return
        filters = self._filters()
        if filters is None:
            self._loaded_filter = None
            self.history_list.clear()
            self.count_label.clear()
            self.empty_label.hide()
            self.more_button.hide()
            return
        append = append and filters == self._loaded_filter and self._next_before is not None
        request = replace(filters, before=self._next_before) if append else filters
        revision = self._revision
        self._busy = True
        self.count_label.setText(_("Loading..."))
        self.more_button.setEnabled(False)

        def done(result):
            self._busy = False
            if self._closed:
                return
            if revision != self._revision:
                self._timer.start()
                return
            if not result.ok:
                self.count_label.setText(_("Could not load notes"))
                self.more_button.setEnabled(True)
                self.error_occurred.emit(result.error)
                return
            page = result.value
            scroll_position = self.history_list.verticalScrollBar().value()
            with QSignalBlocker(self.history_list):
                if not append:
                    self.history_list.clear()
                for preview in page.notes:
                    item = QListWidgetItem(preview.day.isoformat() + "\n" + preview.text)
                    item.setData(Qt.ItemDataRole.UserRole, preview.day)
                    self.history_list.addItem(item)
            self._loaded_filter = filters
            self._next_before = page.next_before
            self.count_label.setText(_("{shown} of {total} dates").format(
                shown=self.history_list.count(), total=page.total))
            self.empty_label.setVisible(not self.history_list.count())
            self.more_button.setVisible(page.next_before is not None)
            self.more_button.setEnabled(True)
            self.set_active_day(self._active_day)
            if append:
                self.history_list.verticalScrollBar().setValue(scroll_position)
        try:
            self._runner.submit("search_notes", lambda _token: self._view_model.browse(request),
                                on_complete=owned_callback(self, done))
        except Exception:
            done(Result.failure(InfrastructureError("note_load_failed", "note_load_failed")))
