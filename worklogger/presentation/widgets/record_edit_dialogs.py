"""Clock-based record boundaries and explicit overlap replacement previews."""

from datetime import date, datetime, timedelta

from PySide6.QtCore import QEvent, QTime, Qt, QSignalBlocker
from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QRadioButton, QStackedWidget, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from worklogger.domain.worklog.editing import split_entry_at, place_historical_break
from worklogger.domain.worklog.models import TimeRange
from worklogger.domain.worklog.rules import entry_interval, parse_time, wall_time_candidates
from worklogger.infrastructure.i18n import _
from worklogger.presentation.date_labels import day_label
from worklogger.presentation.errors import display_error_code
from worklogger.presentation.widgets.assets import apply_window_icon
from worklogger.presentation.widgets.data_tree import configure_data_tree, set_data_tooltips
from worklogger.presentation.widgets.icons import set_button_icon, ui_icon
from worklogger.presentation.widgets.record_timeline import RecordReplacementTimeline
from worklogger.presentation.widgets.time_picker import TimePickerDialog
from worklogger.presentation.entry_type_labels import entry_type_label


def _period_tree():
    tree = QTreeWidget()
    tree.setHeaderLabels([_("Date"), _("Time"), _("Work type"), _("Content")])
    tree.setRootIsDecorated(False)
    configure_data_tree(tree, (115, 145, 140, 160), stretch_column=3)
    tree.setMinimumHeight(110)
    return tree


def _show_periods(tree, periods, *, minimum_rows=1):
    tree.clear()
    for record in sorted(periods, key=lambda item: (item.day, item.start_time or "")):
        span = f"{record.start_time} - {record.end_time}" if record.has_times else _("All day")
        if record.started_at and (record.started_at.second or record.ended_at.second):
            span = f"{record.started_at:%H:%M:%S} - {record.ended_at:%H:%M:%S}"
        if record.is_overnight:
            span += " (+1)"
        content = "\n".join(value for value in (record.context.label, record.note) if value)
        row = QTreeWidgetItem([record.day.isoformat(), span, entry_type_label(record.entry_type),
                              content.splitlines()[0] if content else ""])
        precise_span = (f"{record.started_at.isoformat()} - {record.ended_at.isoformat()}"
                        if record.started_at else span)
        set_data_tooltips(row, {0: day_label(record.day), 1: precise_span, 3: content})
        tree.addTopLevelItem(row)
    visible_rows = max(minimum_rows, min(3, tree.topLevelItemCount()))
    row_height = max(24, tree.sizeHintForRow(0))
    height = tree.header().sizeHint().height() + visible_rows * row_height + 4
    tree.setMinimumHeight(max(tree.minimumHeight(), height) if minimum_rows > 1 else height)


def _section(text):
    label = QLabel(text)
    label.setProperty("role", "section_heading")
    return label


def _message_page(text):
    # Keep blank pages measurable alongside wrapping error messages.
    label = QLabel(text or " ")
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    return label


def _footer(dialog, root, confirm_text, icon):
    row = QHBoxLayout()
    row.addStretch()
    cancel = QPushButton(_("Cancel"))
    cancel.setDefault(True)
    cancel.clicked.connect(dialog.reject)
    row.addWidget(cancel)
    confirm = QPushButton(confirm_text)
    confirm.setAutoDefault(False)
    confirm.setProperty("variant", "primary")
    set_button_icon(confirm, icon)
    confirm.clicked.connect(dialog.accept)
    row.addWidget(confirm)
    root.addLayout(row)
    return confirm


class RecordBoundaryDialog(QDialog):
    def __init__(self, record, parent=None, *, zone=None, historical_break=False):
        super().__init__(parent)
        self.record, self.historical_break = record, historical_break
        self.zone = zone or (record.started_at.tzinfo if record.started_at else None)
        self._choices, self._periods = (), ()
        self.setWindowTitle(_("Place historical break") if historical_break else _("Split record"))
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setObjectName("record_boundary_dialog")
        apply_window_icon(self)
        self.resize(680, 440)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        root.setSpacing(12)
        original = _period_tree()
        _show_periods(original, (record,))
        original.setMinimumHeight(80)
        original.setMaximumHeight(105)
        root.addWidget(original)
        self._start, self._end = (entry_interval(record) if record.started_at else
                                 TimeRange(record.start_time, record.end_time).as_datetimes(record.day))
        initial = self._start + (self._end - self._start) / 2
        if historical_break:
            initial = self._start + timedelta(minutes=min(180, max(0, round(record.raw_hours() * 60) - 1)))
        if record.started_at:
            initial = initial.astimezone(self.zone)
        initial = initial.replace(microsecond=0)
        show_seconds = bool(record.started_at and (record.started_at.second or record.ended_at.second))
        if not show_seconds:
            initial = initial.replace(second=0)
        self._applied_wall = initial.replace(tzinfo=None)
        self._initial_offset = initial.utcoffset()
        self._clock_format = "HH:mm:ss" if show_seconds else "HH:mm"
        self._time_picker = None
        self.time_input = QLineEdit(self._clock_text(initial))
        self.time_input.setMaxLength(8 if show_seconds else 5)
        self.time_input.setPlaceholderText(self._clock_format)
        self.time_input.installEventFilter(self)
        label = _("Break starts") if historical_break else _("Split at")
        self.time_input.setAccessibleName(label)
        clock_action = self.time_input.addAction(ui_icon("clock"), QLineEdit.ActionPosition.TrailingPosition)
        clock_action.setToolTip(_("Select time"))
        clock_action.triggered.connect(self._open_time_picker)
        self.date_combo = QComboBox(self)
        self.date_combo.setAccessibleName(_("Date"))
        first, last = ((moment.astimezone(self.zone).date() for moment in (self._start, self._end))
                       if record.started_at else (self._start.date(), self._end.date()))
        day = first
        while day <= last:
            self.date_combo.addItem(day.isoformat(), day.isoformat())
            if day == last:
                break
            day += timedelta(days=1)
        self.date_combo.setCurrentIndex(self.date_combo.findData(initial.date().isoformat()))
        self.date_combo.setVisible(first != last)
        self.apply_time_button = QToolButton()
        self.reset_time_button = QToolButton()
        for button, icon, caption in ((self.apply_time_button, "check", _("Apply time")),
                                      (self.reset_time_button, "rotate-ccw", _("Discard time change"))):
            set_button_icon(button, icon)
            button.setToolTip(caption)
            button.setAccessibleName(caption)
            button.setProperty("icon_only", True)
            button.setFixedSize(40, 40)
        for field in (self.time_input, self.date_combo):
            field.setFixedHeight(self.apply_time_button.height())
        time_row = QHBoxLayout()
        time_row.setSpacing(8)
        time_row.addWidget(self.date_combo)
        time_row.addWidget(self.time_input, 1)
        time_row.addWidget(self.apply_time_button)
        time_row.addWidget(self.reset_time_button)
        self.offset_combo = QComboBox()
        self.offset_combo.setAccessibleName(_("UTC offset"))
        self.offset_label = QLabel(_("UTC offset"))
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.addRow(label, time_row)
        form.addRow(self.offset_label, self.offset_combo)
        root.addLayout(form)
        root.addWidget(_section(_("Result")))
        self.preview = _period_tree()
        root.addWidget(self.preview, 1)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumHeight(self.status_label.fontMetrics().lineSpacing())
        root.addWidget(self.status_label)
        self.confirm_button = _footer(self, root, _("Save") if historical_break else _("Split record"), "check")
        self.time_input.textChanged.connect(self._pending_changed)
        self.date_combo.currentIndexChanged.connect(self._pending_changed)
        self.apply_time_button.clicked.connect(self._apply_time)
        self.reset_time_button.clicked.connect(self._reset_time)
        self.offset_combo.currentIndexChanged.connect(self._render)
        self._refresh()
        self.time_input.setFocus()

    def _clock_text(self, wall):
        return wall.strftime("%H:%M:%S" if self._clock_format == "HH:mm:ss" else "%H:%M")

    def _entered_clock(self):
        text = self.time_input.text().strip()
        if self._clock_format == "HH:mm:ss":
            clock = QTime.fromString(text, "HH:mm:ss")
            if clock.isValid():
                return clock
        parsed = parse_time(text)
        return QTime.fromString(parsed, "HH:mm") if parsed else None

    def _selected_wall(self):
        clock = self._entered_clock()
        return (datetime.combine(date.fromisoformat(self.date_combo.currentData()), clock.toPython())
                if clock is not None else None)

    def _has_pending_time(self):
        return self._selected_wall() != self._applied_wall

    def _pending_changed(self, *_args):
        pending = self._has_pending_time()
        self.apply_time_button.setEnabled(pending and self._selected_wall() is not None)
        self.reset_time_button.setEnabled(pending)
        self.offset_combo.setEnabled(not pending)
        self._render()

    def _apply_time(self):
        wall = self._selected_wall()
        if wall is not None:
            self._applied_wall = wall
            with QSignalBlocker(self.time_input):
                self.time_input.setText(self._clock_text(wall))
            self._refresh()

    def _reset_time(self):
        with QSignalBlocker(self.time_input), QSignalBlocker(self.date_combo):
            self.date_combo.setCurrentIndex(self.date_combo.findData(self._applied_wall.date().isoformat()))
            self.time_input.setText(self._clock_text(self._applied_wall))
        self._pending_changed()

    def _open_time_picker(self):
        if self._time_picker is not None:
            self._time_picker.raise_()
            return
        clock = self._entered_clock() or QTime(self._applied_wall.hour, self._applied_wall.minute, self._applied_wall.second)
        picker = TimePickerDialog(self.time_input.accessibleName(), clock.toString("HH:mm"), self)
        picker.time_input.setDisplayFormat(self._clock_format)
        picker.time_input.setMaximumTime(QTime(23, 59, 59))
        picker.time_input.setTime(clock)
        self._time_picker = picker
        def selected():
            self.time_input.setText(picker.time_input.time().toString(self._clock_format))
            self._apply_time()
        picker.accepted.connect(selected)
        picker.finished.connect(lambda: setattr(self, "_time_picker", None))
        picker.open()

    def eventFilter(self, watched, event):
        if watched is self.time_input and event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._apply_time()
            return True
        return super().eventFilter(watched, event)

    def chosen_boundary(self):
        index = self.offset_combo.currentIndex()
        return self._choices[index] if 0 <= index < len(self._choices) else None

    def chosen_minutes(self):
        boundary = self.chosen_boundary()
        if boundary is None:
            raise ValueError("time_range_invalid")
        value = (boundary - self._start).total_seconds() / 60
        if abs(value - round(value)) > 1e-8:
            raise ValueError("historical_break_precision_invalid")
        return round(value)

    def _refresh(self, *_args):
        wall = self._applied_wall
        previous = self.chosen_boundary()
        preferred_offset = previous.utcoffset() if previous is not None else self._initial_offset
        self._choices = wall_time_candidates(wall, self.zone) if self.record.started_at else (wall,)
        with QSignalBlocker(self.offset_combo):
            self.offset_combo.clear()
            for index, choice in enumerate(self._choices):
                self.offset_combo.addItem(choice.strftime("%z"))
                if choice.utcoffset() == preferred_offset:
                    self.offset_combo.setCurrentIndex(index)
        self.offset_label.setVisible(len(self._choices) > 1)
        self.offset_combo.setVisible(len(self._choices) > 1)
        self._pending_changed()

    def _render(self, *_args):
        if self._has_pending_time():
            self.status_label.setText(_("Unconfirmed time change"))
            self.confirm_button.setEnabled(False)
            return
        try:
            boundary = self.chosen_boundary()
            if boundary is None:
                raise ValueError("time_range_invalid")
            self._periods = (place_historical_break(self.record, self.chosen_minutes()) if self.historical_break
                             else split_entry_at(self.record, boundary))
            _show_periods(self.preview, self._periods)
            self.status_label.clear()
            self.confirm_button.setEnabled(True)
        except ValueError as error:
            self._periods = ()
            self.preview.clear()
            self.status_label.setText(display_error_code(str(error)))
            self.confirm_button.setEnabled(False)

    def accept(self):
        if self._periods and not self._has_pending_time():
            super().accept()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self._has_pending_time():
            self._apply_time()
            event.accept()
        else:
            super().keyPressEvent(event)


class OverlapReplacementDialog(QDialog):
    def __init__(self, plan, parent=None):
        super().__init__(parent)
        self.plan = plan
        self._valid = False
        self.setObjectName("overlap_replacement_dialog")
        self.setWindowTitle(_("Overlapping records"))
        self.setWindowModality(Qt.WindowModality.WindowModal)
        apply_window_icon(self)
        self.resize(760, 650)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        root.setSpacing(12)
        root.addWidget(_section(_("Existing records")))
        existing = _period_tree()
        _show_periods(existing, plan.affected)
        root.addWidget(existing, 1)
        self.keep_button = QRadioButton(_("Replace overlapping time only"))
        self.whole_button = QRadioButton(_("Replace entire overlapping records"))
        self.keep_button.setChecked(True)
        choices = QHBoxLayout()
        choices.setSpacing(24)
        choices.addWidget(self.keep_button)
        choices.addWidget(self.whole_button)
        choices.addStretch()
        root.addLayout(choices)
        self.message_stack = QStackedWidget()
        self.message_stack.addWidget(_message_page(_("Time outside the new period is preserved. Existing records may be split.")))
        self.message_stack.addWidget(_message_page(_("Entire overlapping records will be removed, including time outside the new period.")))
        root.addWidget(self.message_stack)
        self.timeline = RecordReplacementTimeline(plan, self)
        root.addWidget(self.timeline)
        root.addWidget(_section(_("Result")))
        self.preview = _period_tree()
        root.addWidget(self.preview, 1)
        self.status_stack = QStackedWidget()
        self._previews = {}
        for keep_outside in (True, False):
            try:
                periods = self.plan.periods(keep_outside=keep_outside)
                status = ""
            except ValueError as error:
                periods, status = (), display_error_code(str(error))
            self._previews[keep_outside] = periods
            self.status_stack.addWidget(_message_page(status))
        _show_periods(self.preview, self._previews[False], minimum_rows=3)
        root.addWidget(self.status_stack)
        self.confirm_button = _footer(self, root, _("Replace and save"), "save")
        self.keep_button.toggled.connect(self._refresh)
        self._refresh()
        self.keep_button.setFocus()

    @property
    def keep_outside(self):
        return self.keep_button.isChecked()

    def _refresh(self, *_args):
        self.timeline.set_keep_outside(self.keep_outside)
        index = 0 if self.keep_outside else 1
        self.message_stack.setCurrentIndex(index)
        self.status_stack.setCurrentIndex(index)
        periods = self._previews[self.keep_outside]
        _show_periods(self.preview, periods, minimum_rows=3)
        self._valid = bool(periods)
        self.confirm_button.setEnabled(self._valid)

    def accept(self):
        if self._valid:
            super().accept()
