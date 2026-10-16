"""Date-filtered note previews with asynchronous, cursor-based pagination."""

from dataclasses import replace
from datetime import date

from PySide6.QtCore import QSignalBlocker, QTimer, Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QProgressBar, QPushButton,
    QVBoxLayout, QWidget)

from worklogger.domain.notes.models import NoteHistoryFilter
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import _
from worklogger.presentation.job_runner import owned_callback
from worklogger.presentation.widgets.date_range import DateRangeControls
from worklogger.presentation.widgets.icons import set_button_icon
from worklogger.presentation.widgets.two_line_delegate import TwoLineItemDelegate


class NoteHistoryBrowser(QWidget):
    error_occurred = Signal(object)

    def __init__(self, view_model, day: date, *, job_runner, parent=None):
        super().__init__(parent)
        self._view_model, self._runner = view_model, job_runner
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
        self.date_range = DateRangeControls(day)
        for name in ("mode_input", "period_widget", "period_button", "previous_button",
                     "next_button", "range_widget", "start_input", "end_input"):
            setattr(self, name, getattr(self.date_range, name))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(_("Search notes"))
        self.search_input.setAccessibleName(_("Search notes"))
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMaxLength(256)
        layout.addWidget(self.search_input)
        layout.addWidget(self.date_range)
        self.range_label = QLabel()
        self.count_label = QLabel()
        self.empty_label = QLabel(_("No notes found"))
        for label in (self.range_label, self.count_label, self.empty_label):
            label.setProperty("role", "secondary")
            label.setWordWrap(True)
        layout.addWidget(self.range_label)
        status = QHBoxLayout()
        status.addWidget(self.count_label, 1)
        self.loading_bar = QProgressBar()
        self.loading_bar.setRange(0, 0)
        self.loading_bar.setTextVisible(False)
        self.loading_bar.setFixedSize(72, 6)
        self.loading_bar.setAccessibleName(_("Loading..."))
        self.loading_bar.hide()
        status.addWidget(self.loading_bar)
        layout.addLayout(status)
        layout.addWidget(self.empty_label)
        self.empty_label.hide()
        self.history_list = QListWidget()
        self.history_list.setObjectName("note_history_list_widget")
        self.history_list.setAccessibleName(_("Notes"))
        self.history_list.setMouseTracking(True)
        self.history_list.setItemDelegate(TwoLineItemDelegate(self.history_list))
        self.history_list.setSpacing(4)
        self.history_list.setFrameShape(QFrame.Shape.NoFrame)
        self.history_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.history_list, 1)
        self.more_button = QPushButton(_("Load more"))
        set_button_icon(self.more_button, "chevron-down")
        self.more_button.hide()
        layout.addWidget(self.more_button)
        self.date_range.range_changed.connect(self._filters_changed)
        self.search_input.textChanged.connect(self._filters_changed)
        self.more_button.clicked.connect(lambda: self._load(append=True))

    def _sync_controls(self):
        self.date_range.sync_controls()
        filters = self._filters()
        self.range_label.setText(_("Invalid date range") if filters is None else _("All dates")
                                 if (filters.start, filters.end) == (date.min, date.max)
                                 else f"{filters.start.isoformat()} - {filters.end.isoformat()}")

    def _filters(self):
        text = self.search_input.text().strip()
        start, end = self.date_range.bounds()
        return NoteHistoryFilter(start, end, text) if start <= end else None

    def _filters_changed(self, *_args):
        self._revision += 1
        self._next_before = None
        self.more_button.hide()
        self._sync_controls()
        self._set_loading(self._filters() is not None)
        self._timer.start()

    def refresh(self):
        self._revision += 1
        self._load()

    def stop(self, *_args):
        self._closed = True
        self._timer.stop()
        self._set_loading(False)

    def _set_loading(self, loading):
        self.loading_bar.setVisible(loading)
        self.more_button.setEnabled(not loading)
        self.more_button.setText(_("Loading...") if loading else _("Load more"))
        if loading:
            self.count_label.setText(_("Loading..."))
            self.empty_label.hide()

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
            self._set_loading(False)
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
        self._set_loading(True)

        def done(result):
            self._busy = False
            if self._closed:
                return
            if revision != self._revision:
                self._timer.start()
                return
            self._set_loading(False)
            if not result.ok:
                self.count_label.setText(_("Could not load notes"))
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
            self.set_active_day(self._active_day)
            if append:
                self.history_list.verticalScrollBar().setValue(scroll_position)
        try:
            self._runner.submit("search_notes", lambda _token: self._view_model.browse(request),
                                on_complete=owned_callback(self, done))
        except Exception:
            done(Result.failure(InfrastructureError("note_load_failed", "note_load_failed")))
