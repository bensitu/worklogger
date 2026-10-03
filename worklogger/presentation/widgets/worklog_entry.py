"""Work log entry Qt widget bound to entry ViewModel state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from PySide6.QtCore import QTime, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QTimeEdit,
    QToolButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from worklogger.domain.worklog.models import WorkType
from worklogger.domain.worklog.rules import parse_time
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.viewmodels.auto_record import (
    AutoRecordState,
    AutoRecordViewModel,
)
from worklogger.presentation.viewmodels.worklog_entry import WorkLogEntryForm
from worklogger.presentation.widgets.assets import apply_window_icon
from worklogger.presentation.widgets.icons import set_button_icon, ui_icon


@dataclass(frozen=True)
class WorkLogEntryDraft:
    day: date
    start_time: str | None
    end_time: str | None
    break_hours: float
    note: str
    work_type: str


class _TimePickerDialog(QDialog):
    def __init__(self, title: str, initial_time: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("manual_time_picker_dialog")
        self.setWindowTitle(title)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        apply_window_icon(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        self.time_input = QTimeEdit()
        self.time_input.setObjectName("manual_time_picker_widget")
        self.time_input.setDisplayFormat("HH:mm")
        self.time_input.setKeyboardTracking(False)
        self.time_input.setTimeRange(QTime(0, 0), QTime(23, 59))
        parsed = parse_time(initial_time)
        self.time_input.setTime(QTime.fromString(parsed, "HH:mm") if parsed else QTime.currentTime())
        root.addWidget(self.time_input)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.close_button = QPushButton(_("Close"))
        self.close_button.setObjectName("manual_time_picker_close_button")
        self.close_button.clicked.connect(self.reject)
        buttons.addWidget(self.close_button)
        self.select_button = QPushButton(_("Select"))
        self.select_button.setObjectName("manual_time_picker_select_button")
        self.select_button.setProperty("variant", "primary")
        self.select_button.setDefault(True)
        self.select_button.clicked.connect(self.accept)
        buttons.addWidget(self.select_button)
        root.addLayout(buttons)
        self.setMinimumWidth(260)


class WorkLogEntryPanel(QWidget):
    draft_changed = Signal(object)
    save_requested = Signal(object)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        auto_record_view_model: AutoRecordViewModel | None = None,
        compact: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("worklog_entry_panel_widget")
        self.setProperty("compact", compact)
        self._form: WorkLogEntryForm | None = None
        self._updating = False
        self._applying_auto_state = False
        self._auto_record_view_model = auto_record_view_model or AutoRecordViewModel()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4 if compact else 8)

        self.time_tabs = QTabWidget()
        root.addWidget(self.time_tabs)

        manual_tab = QWidget()
        manual_tab.setObjectName("worklog_manual_tab_widget")
        manual_layout = QVBoxLayout(manual_tab)
        manual_layout.setContentsMargins(0, 0, 0, 0)
        manual_layout.setSpacing(4 if compact else 8)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows if compact else QFormLayout.RowWrapPolicy.WrapLongRows)
        if compact:
            form.setVerticalSpacing(2)
        manual_layout.addLayout(form)
        self.time_tabs.addTab(manual_tab, _("Manual Input"))

        self.start_input = QLineEdit()
        self.start_input.setObjectName("start_time_line_edit")
        self.start_time_action = self.start_input.addAction(ui_icon("clock"), QLineEdit.ActionPosition.TrailingPosition)
        self.start_time_action.setText(_("Start"))
        self.start_time_action.setToolTip(_("Start"))
        self.start_time_action.triggered.connect(lambda: self._open_time_picker(self.start_input, _("Start")))
        self.start_input.textChanged.connect(self._emit_draft_changed)
        form.addRow(_("Start"), self.start_input)

        self.end_input = QLineEdit()
        self.end_input.setObjectName("end_time_line_edit")
        self.end_time_action = self.end_input.addAction(ui_icon("clock"), QLineEdit.ActionPosition.TrailingPosition)
        self.end_time_action.setText(_("End"))
        self.end_time_action.setToolTip(_("End"))
        self.end_time_action.triggered.connect(lambda: self._open_time_picker(self.end_input, _("End")))
        self.end_input.textChanged.connect(self._emit_draft_changed)
        form.addRow(_("End"), self.end_input)

        self.break_input = QDoubleSpinBox()
        self.break_input.setObjectName("break_hours_double_spin_box")
        self.break_input.setRange(0.0, 24.0)
        self.break_input.setSingleStep(0.25)
        self.break_input.setDecimals(2)
        self.break_input.valueChanged.connect(self._emit_draft_changed)
        if compact:
            self.break_input.setAccessibleName(_("Break (h)"))
            unit_layout = QHBoxLayout(self.break_input)
            unit_layout.setContentsMargins(0, 0, 8, 0)
            unit_layout.addStretch()
            unit_label = QLabel(_("h"))
            unit_label.setObjectName("break_hours_unit_label")
            unit_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            unit_layout.addWidget(unit_label)
        form.addRow(_("Break") if compact else _("Break (h)"), self.break_input)

        self.work_type_combo = QComboBox()
        self.work_type_combo.setObjectName("work_type_combo")
        for work_type in WorkType:
            self.work_type_combo.addItem(_work_type_label(work_type), work_type.value)
        self.work_type_combo.currentIndexChanged.connect(self._emit_draft_changed)
        form.addRow(_("Work type"), self.work_type_combo)

        self.note_input = QTextEdit()
        self.note_input.setObjectName("note_text_edit")
        self.note_input.setFixedHeight(88)
        self.note_input.textChanged.connect(self._emit_draft_changed)
        self.note_toggle_button = QToolButton()
        self.note_toggle_button.setObjectName("entry_notes_toggle_button")
        self.note_toggle_button.setText(_("Notes"))
        self.note_toggle_button.setToolTip(_("Notes"))
        self.note_toggle_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.note_toggle_button.setCheckable(True)
        self.note_toggle_button.setIcon(ui_icon("chevron-down"))
        self.note_toggle_button.toggled.connect(self.note_input.setVisible)
        self.note_toggle_button.toggled.connect(
            lambda expanded: self.note_toggle_button.setIcon(ui_icon("chevron-up" if expanded else "chevron-down"))
        )
        if compact:
            manual_layout.addWidget(self.note_toggle_button, 0, Qt.AlignmentFlag.AlignLeft)
            manual_layout.addWidget(self.note_input)
            self.note_input.hide()
        else:
            self.note_toggle_button.hide()
            form.addRow(_("Notes"), self.note_input)

        self.auto_tab = QWidget()
        self.auto_tab.setObjectName("worklog_auto_tab_widget")
        auto_layout = QVBoxLayout(self.auto_tab)
        auto_layout.setContentsMargins(0, 0, 0, 0)
        auto_layout.setSpacing(8)
        auto_buttons = QGridLayout()
        auto_buttons.setSpacing(8)
        auto_buttons.setColumnStretch(0, 1)
        auto_buttons.setColumnStretch(1, 1)
        self.clock_in_button = QPushButton(_("Start"))
        self.clock_in_button.setObjectName("auto_clock_in_button")
        self.clock_out_button = QPushButton(_("End"))
        self.clock_out_button.setObjectName("auto_clock_out_button")
        self.break_button = QPushButton(_("Start break"))
        self.break_button.setObjectName("auto_break_button")
        self.quick_break_button = QPushButton(f"{_('Break')}\n+15{_('m')}")
        self.quick_break_button.setObjectName("auto_quick_break_button")
        self.quick_break_button.setToolTip(_("+15m break"))
        self.quick_break_button.setAccessibleName(_("+15m break"))
        for button in (self.clock_in_button, self.clock_out_button, self.break_button, self.quick_break_button):
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        auto_buttons.addWidget(self.clock_in_button, 0, 0)
        auto_buttons.addWidget(self.clock_out_button, 0, 1)
        auto_buttons.addWidget(self.break_button, 1, 0)
        auto_buttons.addWidget(self.quick_break_button, 1, 1)
        auto_layout.addLayout(auto_buttons)
        self.auto_status_label = QLabel("")
        self.auto_status_label.setObjectName("auto_status_label")
        auto_layout.addWidget(self.auto_status_label)
        auto_layout.addStretch(1)
        self.time_tabs.addTab(self.auto_tab, _("Auto Record"))
        if compact:
            self.time_tabs.currentChanged.connect(self._update_tab_size_policy)
            self._update_tab_size_policy()

        self.auto_timer = QTimer(self)
        self.auto_timer.setInterval(60_000)
        self.auto_timer.timeout.connect(self._refresh_auto_state)
        self.clock_in_button.clicked.connect(self._auto_clock_in)
        self.clock_out_button.clicked.connect(self._auto_clock_out)
        self.break_button.clicked.connect(self._auto_toggle_break)
        self.quick_break_button.clicked.connect(lambda: self._auto_quick_break(15))

        status_row = QHBoxLayout()
        self.hours_label = QLabel("")
        self.hours_label.setObjectName("worklog_hours_label")
        self.status_label = QLabel("")
        self.status_label.setObjectName("entry_status_label")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        status_row.addWidget(self.hours_label)
        status_row.addWidget(self.status_label, 1)
        root.addLayout(status_row)

        self.error_label = QLabel("")
        self.error_label.setObjectName("entry_error_label")
        self.error_label.setWordWrap(True)
        root.addWidget(self.error_label)

        self.save_button = QPushButton(_("Save"))
        self.save_button.setObjectName("save_worklog_button")
        self.save_button.setProperty("variant", "primary")
        set_button_icon(self.save_button, "save")
        self.save_button.clicked.connect(self._emit_save_requested)
        root.addWidget(self.save_button)

    def _open_time_picker(self, field: QLineEdit, title: str) -> None:
        dialog = _TimePickerDialog(title, field.text(), self)
        dialog.accepted.connect(lambda: field.setText(dialog.time_input.time().toString("HH:mm")))
        dialog.open()
        dialog.time_input.setFocus()
        dialog.time_input.setSelectedSection(QTimeEdit.Section.HourSection)

    def current_draft(self) -> WorkLogEntryDraft | None:
        if self._form is None:
            return None
        return WorkLogEntryDraft(
            day=self._form.day,
            start_time=_empty_to_none(self.start_input.text()),
            end_time=_empty_to_none(self.end_input.text()),
            break_hours=float(self.break_input.value()),
            note=self.note_input.toPlainText(),
            work_type=str(self.work_type_combo.currentData() or WorkType.NORMAL.value),
        )

    def _update_tab_size_policy(self, *_args: object) -> None:
        # Inactive pages must not impose their minimum form size on the current tab.
        for index in range(self.time_tabs.count()):
            page = self.time_tabs.widget(index)
            policy = QSizePolicy.Policy.Preferred if index == self.time_tabs.currentIndex() else QSizePolicy.Policy.Ignored
            page.setSizePolicy(policy, policy)
            page.layout().invalidate()
            page.updateGeometry()
        self.time_tabs.updateGeometry()

    def set_form(self, form: WorkLogEntryForm) -> None:
        self._form = form
        self._updating = True
        try:
            self.start_input.setText(form.start_time or "")
            self.end_input.setText(form.end_time or "")
            self.break_input.setValue(float(form.break_hours or 0))
            index = self.work_type_combo.findData(form.work_type)
            self.work_type_combo.setCurrentIndex(index if index >= 0 else 0)
            self.note_input.setPlainText(form.note)
        finally:
            self._updating = False

        self.set_preview_form(form)

    def set_preview_form(self, form: WorkLogEntryForm) -> None:
        # Preview feedback must not rewrite a draft while the user is typing.
        self._form = form
        flags = []
        if form.is_overnight:
            flags.append(_("Overnight"))
        if form.is_leave:
            flags.append(_("Leave"))
        self.hours_label.setText(f"{_('Worked')}: {form.worked_hours:.1f}{_('h')}")
        self.status_label.setText(", ".join(flags))
        self.status_label.setVisible(bool(flags))
        self.error_label.setText(", ".join(form.errors))
        self.error_label.setVisible(bool(form.errors))
        self.save_button.setEnabled(form.can_save)
        self._sync_auto_from_form(form)

    def apply_draft(self, draft: WorkLogEntryDraft) -> None:
        if self._form is None:
            return
        self._updating = True
        try:
            self.start_input.setText(draft.start_time or "")
            self.end_input.setText(draft.end_time or "")
            self.break_input.setValue(float(draft.break_hours or 0))
            index = self.work_type_combo.findData(draft.work_type)
            self.work_type_combo.setCurrentIndex(index if index >= 0 else 0)
            self.note_input.setPlainText(draft.note)
        finally:
            self._updating = False
        self._emit_draft_changed()

    def _emit_save_requested(self) -> None:
        draft = self.current_draft()
        if draft is not None:
            self.save_requested.emit(draft)

    def _emit_draft_changed(self, *_args: object) -> None:
        if self._updating:
            return
        draft = self.current_draft()
        if draft is not None:
            self.draft_changed.emit(draft)

    def _sync_auto_from_form(self, form: WorkLogEntryForm) -> None:
        if self._applying_auto_state:
            return
        self._auto_record_view_model.load_existing(
            day=form.day,
            start_time=form.start_time,
            end_time=form.end_time,
            break_hours=form.break_hours,
            note=form.note,
            work_type=form.work_type,
        )
        self._refresh_auto_state()

    def _auto_clock_in(self) -> None:
        self._auto_record_view_model.set_note(self.note_input.toPlainText())
        self._auto_record_view_model.set_work_type(
            str(self.work_type_combo.currentData() or WorkType.NORMAL.value)
        )
        result = self._auto_record_view_model.start()
        if not result.ok or result.value is None:
            QMessageBox.warning(self, _("Auto Record"), display_error_message(result.error))
            return
        self._apply_auto_state(result.value)

    def _auto_clock_out(self) -> None:
        result = self._auto_record_view_model.finish()
        if not result.ok or result.value is None:
            QMessageBox.warning(self, _("Auto Record"), display_error_message(result.error))
            return
        draft = self._draft_from_auto_values(
            start_time=result.value.start_time,
            end_time=result.value.end_time,
            break_hours=result.value.break_hours,
            note=result.value.note,
            work_type=result.value.work_type,
        )
        if draft is not None:
            self.apply_draft(draft)
        self._refresh_auto_state()

    def _auto_toggle_break(self) -> None:
        state = self._auto_record_view_model.state()
        if state.break_active:
            result = self._auto_record_view_model.end_break()
        elif state.has_recorded_break:
            result = self._auto_record_view_model.continue_break()
        else:
            result = self._auto_record_view_model.restart_break()
        if not result.ok or result.value is None:
            QMessageBox.warning(self, _("Auto Record"), display_error_message(result.error))
            return
        self._apply_auto_state(result.value)

    def _auto_quick_break(self, minutes: int) -> None:
        result = self._auto_record_view_model.add_quick_break(minutes)
        if not result.ok or result.value is None:
            QMessageBox.warning(self, _("Auto Record"), display_error_message(result.error))
            return
        self._apply_auto_state(result.value)

    def _apply_auto_state(self, state: AutoRecordState) -> None:
        draft = self._draft_from_auto_values(
            start_time=state.start_time,
            end_time=state.end_time,
            break_hours=state.break_hours,
            note=state.note,
            work_type=state.work_type,
        )
        if draft is not None:
            # Previewing an auto-record update must not reset its active timer.
            self._applying_auto_state = True
            try:
                self.apply_draft(draft)
            finally:
                self._applying_auto_state = False
        self._refresh_auto_state()

    def _draft_from_auto_values(
        self,
        *,
        start_time: str | None,
        end_time: str | None,
        break_hours: float,
        note: str,
        work_type: str,
    ) -> WorkLogEntryDraft | None:
        if self._form is None:
            return None
        return WorkLogEntryDraft(
            day=self._form.day,
            start_time=start_time,
            end_time=end_time,
            break_hours=break_hours,
            note=note,
            work_type=work_type,
        )

    def _refresh_auto_state(self) -> None:
        state = self._auto_record_view_model.state()
        self.clock_in_button.setText(
            f"{_('Started')}\n{state.start_time}" if state.start_time else _("Start")
        )
        self.clock_out_button.setText(
            f"{_('Ended')}\n{state.end_time}" if state.end_time else _("End")
        )
        self.clock_out_button.setEnabled(state.can_finish)
        self.break_button.setEnabled(bool(state.start_time))
        self.quick_break_button.setEnabled(bool(state.start_time) and not state.break_active)
        if state.break_active:
            minutes = int(round(state.break_hours * 60))
            self.break_button.setText(f"{_('On break')}\n{minutes}{_('m')}")
            self.auto_status_label.setText(_("Break timer running"))
            self.auto_status_label.show()
            if not self.auto_timer.isActive():
                self.auto_timer.start()
        else:
            self.break_button.setText(
                f"{_('Break')}\n{state.break_hours:.2f}{_('h')}"
                if state.has_recorded_break
                else _("Start break")
            )
            self.auto_status_label.clear()
            self.auto_status_label.hide()
            if self.auto_timer.isActive():
                self.auto_timer.stop()


def _empty_to_none(value: str) -> str | None:
    stripped = str(value or "").strip()
    return stripped or None


def _work_type_label(work_type: WorkType) -> str:
    labels = {
        WorkType.NORMAL: _("Normal"),
        WorkType.REMOTE: _("Remote"),
        WorkType.BUSINESS_TRIP: _("Business trip"),
        WorkType.PAID_LEAVE: _("Paid leave"),
        WorkType.COMP_LEAVE: _("Comp leave"),
        WorkType.SICK_LEAVE: _("Sick leave"),
    }
    return labels[work_type]
