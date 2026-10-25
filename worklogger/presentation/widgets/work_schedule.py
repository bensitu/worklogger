"""Validated weekly work-plan editor for account settings."""

from PySide6.QtCore import QLocale, QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QGridLayout, QHBoxLayout,
    QLabel, QPushButton, QRadioButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from worklogger.domain.settings.work_schedule import WorkSchedule
from worklogger.infrastructure.i18n import _, get_language
from worklogger.presentation.widgets.icons import set_button_icon


class WorkScheduleEditor(QWidget):
    schedule_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("work_schedule_editor_widget")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._saved = WorkSchedule()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        self.mode_input = QComboBox()
        self.mode_input.setAccessibleName(_("Work schedule"))
        for caption, mode in ((_("Full month"), "full_month"), (_("One day off per week"), "one_day_off"),
                              (_("Two days off per week"), "two_days_off"),
                              (_("2.5 days off per week"), "two_and_a_half_days_off"), (_("Custom"), "custom")):
            self.mode_input.addItem(caption, mode)
        self.expand_button = QToolButton()
        self.expand_button.setCheckable(True)
        self.expand_button.setToolTip(_("Adjust schedule"))
        self.expand_button.setAccessibleName(_("Adjust schedule"))
        set_button_icon(self.expand_button, "chevron-down")
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self.mode_input, 1)
        header.addWidget(self.expand_button)
        root.addLayout(header)
        self.week_widget = QWidget()
        self.week_widget.setObjectName("work_schedule_week_widget")
        grid = QGridLayout(self.week_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(2)
        grid.setVerticalSpacing(2)
        self.day_groups, self.weekday_labels, self.state_labels = [], [], []
        choices = ((_("Full day"), 2), (_("Half day"), 1), (_("Day off"), 0))
        for row, (caption, _identifier) in enumerate(choices, 1):
            label = QLabel(caption)
            grid.addWidget(label, row, 0)
            self.state_labels.append(label)
        locale = QLocale(get_language())
        for index in range(7):
            weekday = locale.dayName(index + 1)
            label = QLabel(locale.dayName(index + 1, QLocale.FormatType.ShortFormat))
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setToolTip(weekday)
            grid.addWidget(label, 0, index + 1)
            grid.setColumnStretch(index + 1, 1)
            self.weekday_labels.append(label)
            group = QButtonGroup(self)
            for row, (caption, identifier) in enumerate(choices, 1):
                button = QRadioButton()
                button.setObjectName("work_schedule_choice_button")
                button.setFixedSize(28, 28)
                button.setAccessibleName(f"{weekday}: {caption}")
                button.setToolTip(f"{weekday}: {caption}")
                group.addButton(button, identifier)
                grid.addWidget(button, row, index + 1, Qt.AlignmentFlag.AlignCenter)
            group.idToggled.connect(lambda _identifier, checked: self._update_actions() if checked else None)
            self.day_groups.append(group)
        root.addWidget(self.week_widget)
        self.status_label = QLabel()
        self.status_label.setProperty("role", "secondary")
        self.status_label.setWordWrap(True)
        self.save_button = QPushButton(_("Save"))
        self.save_button.setAutoDefault(False)
        set_button_icon(self.save_button, "save")
        self.save_button.clicked.connect(self._save)
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addWidget(self.status_label, 1)
        footer.addWidget(self.save_button)
        root.addLayout(footer)
        self.mode_input.currentIndexChanged.connect(self._mode_changed)
        self.expand_button.toggled.connect(self._update_actions)
        self.set_schedule(self._saved)

    def set_schedule(self, schedule: WorkSchedule):
        if getattr(self, "_initialized", False) and schedule == self._saved:
            return
        changed_mode = self._saved.mode != schedule.mode
        self._saved = schedule
        self._initialized = True
        with QSignalBlocker(self.mode_input):
            self.mode_input.setCurrentIndex(self.mode_input.findData(schedule.mode))
        if changed_mode:
            with QSignalBlocker(self.expand_button):
                self.expand_button.setChecked(schedule.mode == "custom")
        self._set_days(schedule)

    def _set_days(self, schedule):
        for group, weight in zip(self.day_groups, schedule.days):
            with QSignalBlocker(group):
                group.button(int(weight * 2)).setChecked(True)
        self._update_actions()

    def _mode_changed(self):
        with QSignalBlocker(self.expand_button):
            self.expand_button.setChecked(self.mode_input.currentData() == "custom")
        self._set_days(WorkSchedule.preset(self.mode_input.currentData()))

    def _value(self):
        return WorkSchedule(self.mode_input.currentData(), tuple(group.checkedId() / 2 for group in self.day_groups))

    def _update_actions(self, *_args):
        if not hasattr(self, "save_button"):
            return
        mode = self.mode_input.currentData()
        expanded = mode == "custom" or (mode != "full_month" and self.expand_button.isChecked())
        self.expand_button.setVisible(mode not in {"full_month", "custom"})
        self.week_widget.setVisible(expanded)
        set_button_icon(self.expand_button, "chevron-up" if expanded else "chevron-down")
        try:
            value = self._value()
        except ValueError:
            messages = {"one_day_off": _("Exactly one day off is required."),
                        "two_days_off": _("Exactly two days off are required."),
                        "two_and_a_half_days_off": _("Exactly two days off and one half day are required.")}
            self.status_label.setText(messages.get(mode, _("Invalid work schedule")))
            self.save_button.setEnabled(False)
            return
        summary = _("Weekly planned work: {days:g} days").format(days=sum(value.days))
        if not expanded and mode != "full_month":
            locale = QLocale(get_language())
            rest = [locale.dayName(index + 1, QLocale.FormatType.ShortFormat) for index, weight in enumerate(value.days) if weight == 0]
            half = [locale.dayName(index + 1, QLocale.FormatType.ShortFormat) for index, weight in enumerate(value.days) if weight == 0.5]
            summary += "\n" + _("Days off: {days}").format(days=", ".join(rest))
            if half:
                summary += "\n" + _("Half days: {days}").format(days=", ".join(half))
        self.status_label.setText(summary)
        self.save_button.setEnabled(value != self._saved)

    def _save(self):
        if self.save_button.isEnabled():
            self.schedule_changed.emit(self._value().encode())
