"""Clock-based record boundaries and explicit overlap replacement previews."""

from datetime import datetime, timedelta

from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtWidgets import (QComboBox, QDateTimeEdit, QDialog, QFormLayout, QHBoxLayout, QLabel,
    QPushButton, QRadioButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from worklogger.domain.worklog.editing import split_entry_at, place_historical_break
from worklogger.domain.worklog.models import TimeRange
from worklogger.domain.worklog.rules import entry_interval, wall_time_candidates
from worklogger.infrastructure.i18n import _
from worklogger.presentation.date_labels import day_label, duration_label
from worklogger.presentation.errors import display_error_code
from worklogger.presentation.widgets.assets import apply_window_icon
from worklogger.presentation.widgets.data_tree import configure_data_tree, set_data_tooltips
from worklogger.presentation.widgets.date_picker import configure_calendar_popup
from worklogger.presentation.widgets.icons import set_button_icon
from worklogger.presentation.work_type_labels import work_type_label


def _period_tree():
    tree = QTreeWidget()
    tree.setHeaderLabels([_("Date"), _("Time"), _("Work type"), _("Content")])
    tree.setRootIsDecorated(False)
    configure_data_tree(tree, (115, 145, 140, 160), stretch_column=3)
    tree.setMinimumHeight(110)
    return tree


def _show_periods(tree, periods):
    tree.clear()
    for record in sorted(periods, key=lambda item: (item.day, item.start_time or "")):
        span = f"{record.start_time} - {record.end_time}" if record.has_times else _("All day")
        if record.started_at and (record.started_at.second or record.ended_at.second):
            span = f"{record.started_at:%H:%M:%S} - {record.ended_at:%H:%M:%S}"
        if record.is_overnight:
            span += " (+1)"
        content = "\n".join(value for value in (record.context.label, record.note) if value)
        row = QTreeWidgetItem([record.day.isoformat(), span, work_type_label(record.work_type),
                              content.splitlines()[0] if content else ""])
        precise_span = (f"{record.started_at.isoformat()} - {record.ended_at.isoformat()}"
                        if record.started_at else span)
        set_data_tooltips(row, {0: day_label(record.day), 1: precise_span, 3: content})
        tree.addTopLevelItem(row)


def _section(text):
    label = QLabel(text)
    label.setProperty("role", "section_heading")
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
        self.time_input = QDateTimeEdit()
        self.time_input.setDisplayFormat("yyyy-MM-dd HH:mm:ss" if show_seconds else "yyyy-MM-dd HH:mm")
        self.time_input.setKeyboardTracking(False)
        configure_calendar_popup(self.time_input)
        self.time_input.setDateTime(initial.replace(tzinfo=None))
        label = _("Break starts") if historical_break else _("Split at")
        self.time_input.setAccessibleName(label)
        self.offset_combo = QComboBox()
        self.offset_combo.setAccessibleName(_("UTC offset"))
        self.offset_label = QLabel(_("UTC offset"))
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.addRow(label, self.time_input)
        form.addRow(self.offset_label, self.offset_combo)
        root.addLayout(form)
        root.addWidget(_section(_("Result")))
        self.preview = _period_tree()
        root.addWidget(self.preview, 1)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        self.confirm_button = _footer(self, root, _("Save") if historical_break else _("Split record"), "check")
        self.time_input.dateTimeChanged.connect(self._refresh)
        self.offset_combo.currentIndexChanged.connect(self._render)
        self._refresh()
        self.time_input.setFocus()

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
        wall = datetime.combine(self.time_input.date().toPython(), self.time_input.time().toPython())
        self._choices = wall_time_candidates(wall, self.zone) if self.record.started_at else (wall,)
        with QSignalBlocker(self.offset_combo):
            self.offset_combo.clear()
            for choice in self._choices:
                self.offset_combo.addItem(choice.strftime("%z"))
        self.offset_label.setVisible(len(self._choices) > 1)
        self.offset_combo.setVisible(len(self._choices) > 1)
        self._render()

    def _render(self, *_args):
        try:
            boundary = self.chosen_boundary()
            if boundary is None:
                raise ValueError("time_range_invalid")
            self._periods = (place_historical_break(self.record, self.chosen_minutes()) if self.historical_break
                             else split_entry_at(self.record, boundary))
            _show_periods(self.preview, self._periods)
            self.status_label.setText(_("Worked: {hours}").format(
                hours=duration_label(sum(record.worked_hours() for record in self._periods))))
            self.confirm_button.setEnabled(True)
        except ValueError as error:
            self._periods = ()
            self.preview.clear()
            self.status_label.setText(display_error_code(str(error)))
            self.confirm_button.setEnabled(False)

    def accept(self):
        if self._periods:
            super().accept()


class OverlapReplacementDialog(QDialog):
    def __init__(self, plan, parent=None):
        super().__init__(parent)
        self.plan = plan
        self._valid = False
        self.setObjectName("overlap_replacement_dialog")
        self.setWindowTitle(_("Overlapping records"))
        self.setWindowModality(Qt.WindowModality.WindowModal)
        apply_window_icon(self)
        self.resize(720, 590)
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
        root.addWidget(self.keep_button)
        root.addWidget(self.whole_button)
        self.message_label = QLabel()
        self.message_label.setWordWrap(True)
        root.addWidget(self.message_label)
        root.addWidget(_section(_("Result")))
        self.preview = _period_tree()
        root.addWidget(self.preview, 1)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        self.confirm_button = _footer(self, root, _("Replace and save"), "save")
        self.keep_button.toggled.connect(self._refresh)
        self._refresh()
        self.keep_button.setFocus()

    @property
    def keep_outside(self):
        return self.keep_button.isChecked()

    def _refresh(self, *_args):
        self.message_label.setText(_("Time outside the new period is preserved. Existing records may be split.")
            if self.keep_outside else _("Entire overlapping records will be removed, including time outside the new period."))
        try:
            periods = self.plan.periods(keep_outside=self.keep_outside)
            _show_periods(self.preview, periods)
            self.status_label.setText(_("Worked: {hours}").format(hours=duration_label(sum(item.worked_hours() for item in periods))))
            self._valid = True
        except ValueError as error:
            self.preview.clear()
            self.status_label.setText(display_error_code(str(error)))
            self._valid = False
        self.confirm_button.setEnabled(self._valid)

    def accept(self):
        if self._valid:
            super().accept()
