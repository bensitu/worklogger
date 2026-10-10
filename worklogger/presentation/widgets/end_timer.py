"""Explicit timer-end correction with named-zone and offset validation."""

from datetime import datetime, timedelta, timezone
from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtWidgets import QComboBox, QDateTimeEdit, QDialog, QFormLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout
from worklogger.config.constants import MAX_SHIFT_HOURS
from worklogger.domain.worklog.rules import timestamp_span_hours
from worklogger.infrastructure.i18n import _
from worklogger.presentation.date_labels import duration_label
from worklogger.presentation.errors import display_error_code
from worklogger.presentation.widgets.assets import apply_window_icon
from worklogger.presentation.widgets.icons import set_button_icon


class EndTimerDialog(QDialog):
    def __init__(self, started_at, now, zone, parent=None):
        super().__init__(parent)
        self.started_at, self.zone = started_at, zone
        self._candidates = []
        self.setObjectName("end_timer_dialog")
        self.setWindowTitle(_("End recording"))
        self.setWindowModality(Qt.WindowModality.WindowModal)
        apply_window_icon(self)
        self.resize(520, 340)
        maximum = started_at.astimezone(timezone.utc) + timedelta(hours=MAX_SHIFT_HOURS)
        minimum = started_at.astimezone(timezone.utc) + timedelta(seconds=1)
        initial = min(max(now.astimezone(timezone.utc), minimum), maximum).astimezone(zone)
        self._initial_offset = initial.utcoffset()
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        start_label = QLabel(_("Recording started: {time}").format(time=started_at.isoformat(timespec="seconds")))
        start_label.setWordWrap(True)
        root.addWidget(start_label)
        root.addWidget(QLabel(_("Time zone: {zone}").format(zone=str(zone))))
        self.end_input = QDateTimeEdit()
        self.end_input.setObjectName("timer_end_date_time_widget")
        self.end_input.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.end_input.setCalendarPopup(True)
        self.end_input.setDateTime(initial.replace(tzinfo=None))
        self.end_input.setAccessibleName(_("End"))
        self.offset_combo = QComboBox()
        self.offset_combo.setObjectName("timer_end_offset_combo")
        self.offset_label = QLabel(_("UTC offset"))
        self.offset_label.setBuddy(self.offset_combo)
        self.offset_combo.setAccessibleName(_("UTC offset"))
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.addRow(_("End"), self.end_input)
        form.addRow(self.offset_label, self.offset_combo)
        root.addLayout(form)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        root.addStretch()
        footer = QHBoxLayout()
        self.cancel_button = QPushButton(_("Cancel"))
        self.end_button = QPushButton(_("End"))
        self.end_button.setProperty("variant", "primary")
        set_button_icon(self.end_button, "check")
        self.cancel_button.setAutoDefault(False)
        self.end_button.setDefault(True)
        footer.addStretch()
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.end_button)
        root.addLayout(footer)
        self.cancel_button.clicked.connect(self.reject)
        self.end_button.clicked.connect(self.accept)
        self.end_input.dateTimeChanged.connect(self._refresh)
        self.offset_combo.currentIndexChanged.connect(self._status)
        self._refresh()

    def _refresh(self, *_args):
        wall = datetime.combine(self.end_input.date().toPython(), self.end_input.time().toPython())
        choices = []
        for fold in (0, 1):
            try:
                candidate = wall.replace(tzinfo=self.zone, fold=fold)
                utc = candidate.astimezone(timezone.utc)
                if utc.astimezone(self.zone).replace(tzinfo=None) == wall and not any(utc == item.astimezone(timezone.utc) for item in choices):
                    choices.append(candidate)
            except (OverflowError, ValueError):
                continue
        self._candidates = choices
        with QSignalBlocker(self.offset_combo):
            self.offset_combo.clear()
            selected = 0
            for index, candidate in enumerate(choices):
                self.offset_combo.addItem(candidate.strftime("%z"), index)
                if candidate.utcoffset() == self._initial_offset:
                    selected = index
            self.offset_combo.setCurrentIndex(selected)
        self.offset_label.setVisible(len(choices) > 1)
        self.offset_combo.setVisible(len(choices) > 1)
        self._status()

    def chosen_end(self):
        index = self.offset_combo.currentIndex()
        if index < 0 or index >= len(self._candidates):
            return None
        end = self._candidates[index]
        return end if 0 < timestamp_span_hours(self.started_at, end) <= MAX_SHIFT_HOURS else None

    def _status(self, *_args):
        end = self.chosen_end()
        self.end_button.setEnabled(end is not None)
        self.status_label.setText(_("Recorded duration: {duration}").format(duration=duration_label(timestamp_span_hours(self.started_at, end)))
                                  if end is not None else display_error_code("time_range_invalid"))

    def accept(self):
        if self.chosen_end() is not None:
            super().accept()
