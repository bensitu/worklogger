"""Compact editor for individually recorded work periods."""

from datetime import date
import math

from PySide6.QtCore import QEvent, QTimer, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QMenu, QInputDialog, QSizePolicy, QStyle, QStyleOptionTabWidgetFrame,
    QTabWidget, QTextEdit, QToolButton, QVBoxLayout, QWidget)

from worklogger.domain.worklog.models import CustomWorkType, WorkLog, WorkType, TimeRange
from worklogger.domain.worklog.editing import split_entry, place_historical_break
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.errors import ConflictError
from worklogger.config.constants import MAX_SHIFT_HOURS
from worklogger.presentation.widgets.end_timer import EndTimerDialog
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import _
from worklogger.presentation.date_labels import duration_label, day_label
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.viewmodels.time_entries import TimeEntryViewModel
from worklogger.presentation.widgets.icons import set_button_icon, ui_icon
from worklogger.presentation.widgets.time_picker import TimePickerDialog
from worklogger.presentation.widgets.work_context_picker import WorkContextPicker
from worklogger.presentation.work_type_labels import work_type_label


class TimeEntryPanel(QWidget):
    recording_changed = Signal()
    records_changed = Signal(object)
    dirty_changed = Signal(bool)
    busy_changed = Signal(bool)
    selection_changed = Signal(object)
    reminder = Signal(str)

    def __init__(self, view_model: TimeEntryViewModel, *, compact: bool = True, parent=None, job_runner=None):
        super().__init__(parent)
        self.view_model = view_model
        self._job_runner = job_runner
        self.is_busy = False
        self._updating = False
        self._timer_failed = False
        self._reminder_capture = None
        self._notified_reminders = set()
        self._end_dialog = None
        self._day = view_model.draft.day
        self.setObjectName("worklog_entry_panel_widget")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setProperty("compact", compact)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        root.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.time_tabs = QTabWidget()
        self.time_tabs.setObjectName("worklog_mode_tab_widget")
        self.time_tabs.setDocumentMode(True)
        self.time_tabs.tabBar().setObjectName("worklog_mode_selector_widget")
        self.time_tabs.tabBar().setExpanding(True)
        self.time_tabs.tabBar().setDrawBase(False)
        self._mode_height_pending = False
        self.time_tabs.installEventFilter(self)
        root.addWidget(self.time_tabs)
        manual = QWidget()
        manual.setObjectName("worklog_manual_tab_widget")
        manual_layout = QHBoxLayout(manual)
        manual_layout.setContentsMargins(0, 0, 0, 0)
        manual_layout.setSpacing(8)
        self.start_input = self._time_input("start_time_line_edit", _("Start"))
        self.end_input = self._time_input("end_time_line_edit", _("End"))
        for label, field in ((_("Start"), self.start_input), (_("End"), self.end_input)):
            column = QVBoxLayout()
            column.setSpacing(3)
            column.addWidget(QLabel(label))
            column.addWidget(field)
            manual_layout.addLayout(column, 1)
        self.time_tabs.addTab(manual, _("Manual Input"))
        auto = QWidget()
        auto.setObjectName("worklog_auto_tab_widget")
        auto_layout = QVBoxLayout(auto)
        auto_layout.setContentsMargins(0, 0, 0, 0)
        auto_layout.setSpacing(6)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.clock_in_button = QPushButton(_("Start"))
        self.clock_out_button = QPushButton(_("End"))
        for button, name, icon in ((self.clock_in_button, "auto_clock_in_button", "clock"),
                                   (self.clock_out_button, "auto_clock_out_button", "check")):
            button.setObjectName(name)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            set_button_icon(button, icon)
            buttons.addWidget(button)
        auto_layout.addLayout(buttons)
        self.break_button = QPushButton()
        self.break_button.setObjectName("auto_break_button")
        self.break_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        break_row = QHBoxLayout()
        break_row.setSpacing(8)
        break_row.addWidget(self.break_button, 1)
        self.discard_timer_button = QPushButton(_("Discard timer"))
        self.discard_timer_button.setObjectName("discard_timer_button")
        set_button_icon(self.discard_timer_button, "trash")
        self.discard_timer_button.clicked.connect(self._discard_timer)
        break_row.addWidget(self.discard_timer_button, 1)
        auto_layout.addLayout(break_row)
        self.auto_status_label = QLabel()
        self.auto_status_label.setObjectName("auto_status_label")
        self.auto_status_label.setWordWrap(True)
        auto_layout.addWidget(self.auto_status_label)
        self.time_tabs.addTab(auto, _("Auto Record"))

        self.work_type_combo = QComboBox()
        self.work_type_combo.setObjectName("work_type_combo")
        self.work_type_combo.setMinimumWidth(0)
        self.work_type_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.work_type_combo.setMinimumContentsLength(1)
        self._custom_types = ()
        self._reload_work_types()
        classification_row = QHBoxLayout()
        classification_row.setContentsMargins(0, 0, 0, 0)
        classification_row.setSpacing(8)
        classification_row.setAlignment(Qt.AlignmentFlag.AlignTop)
        type_column = QVBoxLayout()
        type_column.setSpacing(3)
        type_column.setAlignment(Qt.AlignmentFlag.AlignTop)
        type_caption = QLabel(_("Work type"))
        type_caption.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        type_caption.setBuddy(self.work_type_combo)
        type_caption.setMinimumHeight(28)
        type_column.addWidget(type_caption)
        type_column.addWidget(self.work_type_combo)
        classification_row.addLayout(type_column, 1)
        self.context_picker = WorkContextPicker(self)
        self.context_picker.setVisible(view_model.projects_available)
        classification_row.addWidget(self.context_picker, 2)
        root.addLayout(classification_row)
        inventory = view_model.project_inventory()
        self._context_error = inventory.error
        if inventory.ok:
            self.context_picker.set_inventory(*inventory.value)
        recent = view_model.recent_contexts()
        if recent.ok:
            self.context_picker.set_recent(recent.value)
        content_heading = QHBoxLayout()
        content_heading.addWidget(QLabel(_("Content")), 1)
        self.polish_button = QToolButton()
        self.polish_button.setObjectName("polish_time_entry_button")
        self.polish_button.setToolTip(_("Polish text"))
        self.polish_button.setAccessibleName(_("Polish text"))
        self.polish_button.setIcon(ui_icon("sparkles", accent=True))
        self.polish_button.setVisible(view_model.rewrite_available)
        self.polish_button.clicked.connect(self._polish_content)
        content_heading.addWidget(self.polish_button)
        root.addLayout(content_heading)
        self.content_input = QTextEdit()
        self.content_input.setObjectName("time_entry_content_text_edit")
        self.content_input.setAcceptRichText(False)
        self.content_input.setFixedHeight(76)
        root.addWidget(self.content_input)
        self.hours_label = QLabel()
        self.hours_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.hours_label.setObjectName("worklog_hours_label")
        root.addWidget(self.hours_label)
        self.actions_widget = QWidget()
        self.actions_widget.setObjectName("time_entry_actions_widget")
        actions = QHBoxLayout(self.actions_widget)
        actions.setContentsMargins(0, 0, 0, 0)
        self.save_button = QPushButton(_("Save"))
        self.save_button.setObjectName("save_worklog_button")
        self.save_button.setProperty("variant", "primary")
        set_button_icon(self.save_button, "save")
        actions.addWidget(self.save_button, 1)
        self.clear_button = QToolButton()
        self.clear_button.setObjectName("clear_time_entry_button")
        self.clear_button.setIcon(ui_icon("eraser"))
        self.clear_button.setToolTip(_("Clear input"))
        self.clear_button.setAccessibleName(_("Clear input"))
        actions.addWidget(self.clear_button)
        self.undo_button = QToolButton()
        self.undo_button.setObjectName("undo_record_change_button")
        self.undo_button.setIcon(ui_icon("rotate-ccw"))
        self.undo_button.setToolTip(_("Undo latest record change"))
        self.undo_button.setAccessibleName(_("Undo latest record change"))
        self.undo_button.setVisible(view_model.changes_available)
        self.undo_button.clicked.connect(self._undo_record_change)
        actions.addWidget(self.undo_button)
        root.addWidget(self.actions_widget)
        self.history_label = QLabel()
        self.history_label.setObjectName("time_entry_history_label")
        self.history_label.setProperty("role", "secondary")
        self.history_label.setWordWrap(True)
        root.addWidget(self.history_label)

        self.time_tabs.currentChanged.connect(self._mode_changed)
        for field in (self.start_input, self.end_input):
            field.textChanged.connect(self._draft_changed)
        self.work_type_combo.currentIndexChanged.connect(self._draft_changed)
        self.context_picker.changed.connect(self._draft_changed)
        self.content_input.textChanged.connect(self._draft_changed)
        self.clock_in_button.clicked.connect(self._start)
        self.clock_out_button.clicked.connect(self._finish)
        self.break_button.clicked.connect(self._break)
        self.save_button.clicked.connect(self._save)
        self.clear_button.clicked.connect(self._clear)
        self.auto_timer = QTimer(self)
        self.auto_timer.setInterval(1000)
        self.auto_timer.timeout.connect(self._tick)
        if self.view_model.timer is not None:
            self.time_tabs.setCurrentIndex(1)
        self._render_editor()

    def _time_input(self, name, title):
        field = QLineEdit()
        field.setObjectName(name)
        field.setAccessibleName(title)
        field.setMinimumWidth(0)
        field.setPlaceholderText("HH:mm")
        action = field.addAction(ui_icon("clock"), QLineEdit.ActionPosition.TrailingPosition)
        action.setToolTip(title)
        action.triggered.connect(lambda: self._pick_time(field, title))
        return field

    def _reload_work_types(self):
        result = self.view_model.list_work_types()
        if result.ok:
            self._custom_types = result.value
        self._populate_work_types()
        return result

    def _populate_work_types(self):
        self.work_type_combo.clear()
        for definition in (WorkType.NORMAL, WorkType.REMOTE, WorkType.BUSINESS_TRIP,
                WorkType.MEETING, WorkType.TRAINING, WorkType.BREAK,
                WorkType.PAID_LEAVE, WorkType.COMP_LEAVE, WorkType.SICK_LEAVE):
            self.work_type_combo.addItem(work_type_label(definition), definition.value)
        for definition in self._custom_types:
            if not definition.archived:
                self.work_type_combo.addItem(definition.label, definition.value)
        self.work_type_combo.addItem(work_type_label(WorkType.OTHER), WorkType.OTHER.value)

    def refresh_work_types(self):
        self._updating = True
        result = self._reload_work_types()
        self._updating = False
        if not result.ok:
            self._apply_result(result, refresh=False)
        self._render_editor()
        return result.ok

    def _pick_time(self, field, title):
        dialog = TimePickerDialog(title, field.text(), self)
        dialog.accepted.connect(lambda: field.setText(dialog.time_input.time().toString("HH:mm")))
        dialog.open()

    def refresh_projects(self):
        def completed(result):
            if result.ok:
                self._context_error = None
                self._updating = True
                self.context_picker.set_inventory(*result.value)
                recent = self.view_model.recent_contexts()
                if recent.ok:
                    self.context_picker.set_recent(recent.value)
                self._updating = False
                self._render_editor()
            else:
                self._apply_result(result, refresh=False)
        self._submit(self.view_model.project_inventory, refresh=False, on_complete=completed)

    @property
    def is_dirty(self):
        return self.view_model.manual_dirty or self.view_model.auto_dirty

    def load_day(self, day: date):
        self._day = day
        result = self.view_model.load(day)
        if result.ok:
            self._render_editor()
            self.hours_label.setText(_("Worked: {hours}").format(hours=duration_label(sum(entry.worked_hours() for entry in result.value))))
        return result

    def edit_entry(self, record: WorkLog):
        if self.is_busy:
            return
        if self.view_model.manual_dirty and not self._confirm_discard():
            self.selection_changed.emit(self.view_model.draft.original.id if self.view_model.draft.original else None)
            return
        loaded = self.view_model.get_entry(record.id)
        if not loaded.ok:
            self._apply_result(loaded, refresh=False)
            return
        self.view_model.select(loaded.value)
        self.time_tabs.setCurrentIndex(0)
        self._render_editor()
        self.start_input.setFocus()

    def copy_event(self, event):
        if self.is_busy or self.view_model.manual_dirty and not self._confirm_discard():
            return
        self.view_model.new(event.day)
        self.time_tabs.setCurrentIndex(0)
        self.view_model.update(start=event.start_time or "", end="00:00" if event.end_time == "24:00" else event.end_time or "", work_type="meeting",
                               content="\n".join(part for part in (event.summary, event.description, event.location) if part))
        self._render_editor()

    def _mode_changed(self, *_args):
        self._render_editor()

    def _draft_changed(self, *_args):
        if self._updating:
            return
        if self.time_tabs.currentIndex() == 0:
            self.view_model.update(start=self.start_input.text(), end=self.end_input.text(),
                                   work_type=str(self.work_type_combo.currentData()), content=self.content_input.toPlainText(),
                                   context=self.context_picker.context())
        else:
            self.view_model.auto_content = self.content_input.toPlainText()
            if self.view_model.timer is None:
                self.view_model.auto_work_type = str(self.work_type_combo.currentData())
                self.view_model.auto_context = self.context_picker.context()
        self._update_actions()
        self.dirty_changed.emit(self.is_dirty)

    def _render_editor(self):
        self._updating = True
        try:
            auto = self.time_tabs.currentIndex() == 1
            draft = self.view_model.draft
            self.start_input.setText(draft.start)
            self.end_input.setText(draft.end)
            work_type = self.view_model.auto_work_type if auto else draft.work_type
            self._populate_work_types()
            snapshot = self.view_model.timer.work_type if auto and self.view_model.timer else draft.original.work_type if not auto and draft.original else None
            if snapshot is None:
                snapshot = next((definition for definition in self._custom_types if definition.value == work_type), None)
            if isinstance(snapshot, CustomWorkType) and self.work_type_combo.findData(work_type) < 0:
                self.work_type_combo.insertItem(self.work_type_combo.count() - 1, snapshot.label, snapshot.value)
            elif isinstance(snapshot, CustomWorkType):
                self.work_type_combo.setItemText(self.work_type_combo.findData(work_type), snapshot.label)
            self.work_type_combo.setCurrentIndex(max(0, self.work_type_combo.findData(work_type)))
            self.work_type_combo.setToolTip(self.work_type_combo.currentText())
            self.content_input.setPlainText(self.view_model.auto_content if auto else draft.content)
            self.work_type_combo.setEnabled(not (auto and self.view_model.timer))
            self.context_picker.set_context(self.view_model.timer.context if auto and self.view_model.timer else
                                           self.view_model.auto_context if auto else draft.context)
            self.context_picker.setEnabled(self._context_error is None and not (auto and self.view_model.timer))
            legacy = draft.original.break_hours if not auto and draft.original else 0
            self.history_label.setText(_("Historical break deduction: {hours}").format(hours=duration_label(legacy)) if legacy else "")
            if self._context_error is not None:
                self.history_label.setText(display_error_message(self._context_error))
            self.history_label.setVisible(bool(legacy) or self._context_error is not None)
        finally:
            self._updating = False
        self._update_actions()
        self.selection_changed.emit(self.view_model.draft.original.id if not auto and self.view_model.draft.original else None)
        self.dirty_changed.emit(self.is_dirty)

    def _update_actions(self):
        self.polish_button.setVisible(self.view_model.rewrite_available)
        self.polish_button.setEnabled(not self.is_busy and self.view_model.rewrite_available and bool(self.content_input.toPlainText().strip()))
        auto = self.time_tabs.currentIndex() == 1
        timer = self.view_model.timer
        self.undo_button.setEnabled(not self.is_busy and timer is None and not self.view_model.restore_failed
                                    and self.view_model.latest_change_info is not None)
        tick = getattr(self, "auto_timer", None)
        if tick is not None:
            if timer and not self._timer_failed and not tick.isActive():
                tick.start()
            elif not timer and tick.isActive():
                tick.stop()
        self.clock_in_button.setEnabled(timer is None and not self.view_model.restore_failed)
        self.clock_out_button.setEnabled(timer is not None)
        self.discard_timer_button.setEnabled(timer is not None or self.view_model.restore_failed)
        self.break_button.setText(_("Break {hours}").format(hours=duration_label(self.view_model.default_break_hours)))
        self.break_button.setEnabled(timer is None and not self.view_model.restore_failed and self.view_model.default_break_hours > 0)
        self.save_button.setText(_("Save content") if auto else _("Save changes") if self.view_model.draft.original else _("Save"))
        self.save_button.setEnabled(self.view_model.auto_dirty and bool(timer or self.view_model.auto_completed) if auto else self.view_model.manual_dirty)
        if timer and timer.pending_end:
            self.clock_out_button.setText(_("Save"))
            self.break_button.setEnabled(False)
            self.auto_status_label.setText(_("Unsaved changes") + f": {timer.started_at:%H:%M} - {timer.pending_end:%H:%M}")
            self.auto_status_label.show()
        elif timer:
            self.clock_out_button.setText(_("End"))
            self._update_elapsed_label()
            self.auto_status_label.show()
        else:
            self.auto_status_label.clear()
            self.auto_status_label.hide()
        if self.view_model.restore_failed:
            self.auto_status_label.setText(_("Unable to restore the timer. Discard it to start a new record."))
            self.auto_status_label.show()
            self.break_button.setEnabled(False)
        self.recording_changed.emit()

    def _update_elapsed_label(self):
        timer = self.view_model.timer
        if timer and not timer.pending_end:
            status = _("Recording since {time} - {duration}").format(
                time=f"{day_label(timer.started_at.date())} {timer.started_at:%H:%M}",
                duration=duration_label(self.view_model.elapsed_hours()))
            if self._reminder_capture != timer.capture_id:
                self._reminder_capture = timer.capture_id
                self._notified_reminders.clear()
            messages = {"duration_limit": _("Choose an earlier end time to save this timer."),
                        "long_timer": _("This timer has reached your reminder duration."),
                        "continuous_timer": _("This work timer has reached your continuous-work reminder duration.")}
            reasons = self.view_model.reminder_reasons()
            for reason in reasons:
                if reason not in self._notified_reminders:
                    self._notified_reminders.add(reason)
                    message = messages[reason]
                    QTimer.singleShot(0, self, lambda message=message: self.reminder.emit(message))
            if reasons:
                status += "\n" + messages[reasons[0]]
            self.auto_status_label.setText(status)

    def recording_action_state(self):
        can_start = not self.is_busy and self.view_model.timer is None and not self.view_model.restore_failed
        can_end = not self.is_busy and self.view_model.timer is not None
        return can_start, can_end

    def start_recording(self):
        if self.recording_action_state()[0]:
            self._start_with_content(self.view_model.auto_work_type, self.view_model.auto_content)

    def end_recording(self):
        if self.recording_action_state()[1]:
            self._finish()

    def eventFilter(self, watched, event):
        if watched is self.time_tabs and event.type() in (QEvent.Type.Resize, QEvent.Type.LayoutRequest, QEvent.Type.StyleChange, QEvent.Type.FontChange):
            if not self._mode_height_pending:
                self._mode_height_pending = True
                QTimer.singleShot(0, self, self._fit_mode_height)
        return super().eventFilter(watched, event)

    def _fit_mode_height(self):
        self._mode_height_pending = False
        if self.time_tabs.currentWidget() is None:
            return
        option = QStyleOptionTabWidgetFrame()
        self.time_tabs.initStyleOption(option)
        content = self.time_tabs.style().subElementRect(QStyle.SubElement.SE_TabWidgetTabContents, option, self.time_tabs)
        page = self.time_tabs.currentWidget()
        page.ensurePolished()
        for widget in page.findChildren(QWidget):
            widget.ensurePolished()
        page.layout().invalidate()
        page_height = max(page.sizeHint().height(), page.layout().totalHeightForWidth(max(1, content.width())))
        required_height = page_height + max(self.time_tabs.tabBar().sizeHint().height(), self.time_tabs.height() - content.height())
        if self.time_tabs.height() != required_height:
            self.time_tabs.setFixedHeight(required_height)

    def _apply_result(self, result, *, refresh=True):
        if not result.ok:
            QMessageBox.warning(self, _("WorkLogger"), display_error_message(result.error))
            return False
        self._timer_failed = False
        recent = self.view_model.recent_contexts()
        if recent.ok:
            self.context_picker.set_recent(recent.value)
        self._render_editor()
        if refresh:
            record = result.value
            timer = self.view_model.timer
            day = record.day if isinstance(record, WorkLog) else timer.started_at.date() if timer else self._day
            self.records_changed.emit(day)
        return True

    def _submit(self, operation, *, refresh=True, automatic=False, on_complete=None):
        if self.is_busy:
            return
        if self._job_runner is None:
            result = operation()
            if on_complete is None:
                self._apply_result(result, refresh=refresh)
            else:
                on_complete(result)
            return
        self.is_busy = True
        self.auto_timer.stop()
        self.setEnabled(False)
        self.busy_changed.emit(True)

        def complete(result):
            self.is_busy = False
            self.setEnabled(True)
            self.busy_changed.emit(False)
            if automatic and not result.ok:
                self._timer_failed = True
            if on_complete is None:
                self._apply_result(result, refresh=refresh and (not automatic or result.value is not None))
            else:
                on_complete(result)

        try:
            self._job_runner.submit("time_entry_update", lambda _token: operation(), on_complete=complete)
        except Exception:
            self.is_busy = False
            self.setEnabled(True)
            self.busy_changed.emit(False)
            self._update_actions()
            self._apply_result(Result.failure(InfrastructureError("worklog_save_failed", "worklog_save_failed")), refresh=False)

    def _save(self):
        self._submit(self.view_model.save_content if self.time_tabs.currentIndex() == 1 else self.view_model.save_manual)

    def _polish_content(self):
        content = self.content_input.toPlainText()
        def complete(result):
            if result.ok:
                self.content_input.setPlainText(result.value)
            else:
                self._apply_result(result, refresh=False)
            self._update_actions()
        self._submit(lambda: self.view_model.rewrite_content(content), refresh=False, on_complete=complete)

    def _start(self):
        work_type, content = str(self.work_type_combo.currentData()), self.content_input.toPlainText()
        self._start_with_content(work_type, content)

    def _start_with_content(self, work_type, content):
        moment = self.view_model.now()
        self._submit(lambda: self.view_model.start(work_type, content, now=moment), refresh=False,
                     on_complete=lambda result: self._complete_start(result, work_type, content, moment))

    def refresh_ai_availability(self):
        self._update_actions()

    def _complete_start(self, result, work_type, content, moment):
        if result.error is None or result.error.code != "fixed_break_active":
            self._apply_result(result, refresh=False)
            return
        dialog = QMessageBox(QMessageBox.Icon.Question, _("End break early?"),
            _("End the break at {time} and start recording work? The saved break duration will be shortened.").format(time=moment.strftime("%H:%M")),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        dialog.button(QMessageBox.StandardButton.Yes).setText(_("Start"))
        dialog.button(QMessageBox.StandardButton.No).setText(_("Cancel"))
        answer = dialog.exec()
        dialog.deleteLater()
        if answer == QMessageBox.StandardButton.Yes:
            record = result.error.details["break_entry"]
            self._submit(lambda: self.view_model.start(work_type, content, now=moment, break_entry=record))

    def _finish(self):
        moment = self.view_model.now()
        timer = self.view_model.timer
        if timer and timer.pending_end is None and self.view_model.elapsed_hours() > MAX_SHIFT_HOURS:
            if self._end_dialog is not None:
                self._end_dialog.raise_()
                self._end_dialog.activateWindow()
                return
            dialog = EndTimerDialog(timer.started_at, moment, moment.tzinfo, self)
            self._end_dialog = dialog
            capture_id = timer.capture_id
            def accepted():
                end = dialog.chosen_end()
                def finish_corrected():
                    current = self.view_model.timer
                    if current is None or current.capture_id != capture_id:
                        return Result.failure(ConflictError("time_entry_timer_conflict", "time_entry_timer_conflict"))
                    return self.view_model.finish(now=end)
                self._submit(finish_corrected)
            dialog.accepted.connect(accepted)
            dialog.finished.connect(lambda: setattr(self, "_end_dialog", None))
            dialog.finished.connect(dialog.deleteLater)
            dialog.open()
            return
        def finish():
            advanced = self.view_model.advance(now=moment)
            return self.view_model.finish(now=moment) if advanced.ok else advanced
        self._submit(finish)

    def _break(self):
        if self.view_model.restore_failed:
            return
        moment = self.view_model.now()
        self._submit(lambda: self.view_model.take_break(now=moment))

    def _tick(self):
        if self.is_busy:
            return
        if self.view_model.resume_due:
            self._submit(self.view_model.advance, automatic=True)
        else:
            self._update_elapsed_label()

    def _clear(self):
        if self.time_tabs.currentIndex() == 1:
            self.view_model.auto_content = ""
        else:
            self.view_model.clear(self._day)
        self._render_editor()

    def new_record(self):
        if self.is_busy or self.view_model.manual_dirty and not self._confirm_discard():
            return False
        self.view_model.clear(self._day)
        self.time_tabs.setCurrentIndex(0)
        self._render_editor()
        self.start_input.setFocus()
        return True

    def _confirm_discard(self):
        return QMessageBox.question(self, _("Discard changes?"), _("You have unsaved work log changes. Discard them?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def _discard_timer(self):
        if QMessageBox.question(self, _("Discard timer"), _("Discard the saved timer without creating a record?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self._submit(self.view_model.discard_timer)

    def delete_entry(self, record: WorkLog):
        if self.is_busy:
            return
        if QMessageBox.question(self, _("Delete record"), _("Delete this time record?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self._submit(lambda: self.view_model.delete_entry(record))

    def record_actions(self, record, position):
        menu = QMenu(self)
        available = not self.is_busy and self.view_model.timer is None and not self.view_model.restore_failed
        split = menu.addAction(ui_icon("pencil"), _("Split record"))
        split.setEnabled(available and record.has_times and not record.break_hours and record.raw_hours() * 60 > 1)
        split.triggered.connect(lambda: self._split_record(record))
        previous = self.view_model.merge_candidate(record)
        merge = menu.addAction(ui_icon("link"), _("Merge with previous record"))
        merge.setEnabled(available and previous is not None)
        merge.triggered.connect(lambda: self._merge_record(previous, record))
        rest = menu.addAction(ui_icon("clock"), _("Place historical break"))
        rest.setEnabled(available and record.has_times and record.break_hours > 0 and not record.is_break)
        rest.triggered.connect(lambda: self._place_break(record))
        menu.addSeparator()
        undo = menu.addAction(ui_icon("rotate-ccw"), _("Undo latest record change"))
        undo.setEnabled(available)
        undo.triggered.connect(self._undo_record_change)
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(position)

    def _changes_confirmed(self):
        return not self.is_dirty or self._confirm_discard()

    def _split_record(self, record):
        if not self._changes_confirmed():
            return
        minutes, confirmed = QInputDialog.getInt(self, _("Split record"), _("First part duration (minutes)"),
            max(1, math.floor(record.raw_hours() * 30)), 1, max(1, math.ceil(record.raw_hours() * 60) - 1))
        if confirmed:
            try:
                preview = split_entry(record, minutes)
            except ValueError as error:
                from worklogger.presentation.errors import display_error_code
                QMessageBox.warning(self, _("Split record"), display_error_code(str(error)))
                return
            if self._confirm_periods(_("Split record"), preview):
                self._submit(lambda: self.view_model.split(record, minutes))

    def _merge_record(self, previous, record):
        if previous is not None and self._changes_confirmed() and QMessageBox.question(self, _("Merge records"),
                _("Merge these adjacent records? Their content will be combined."), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self._submit(lambda: self.view_model.merge(previous, record))

    def _place_break(self, record):
        if not self._changes_confirmed():
            return
        maximum = max(0, math.floor(record.raw_hours() * 60))
        minutes, confirmed = QInputDialog.getInt(self, _("Place historical break"),
            _("Minutes from the record start to the break start"), min(180, maximum), 0, maximum)
        if confirmed:
            try:
                preview = place_historical_break(record, minutes)
            except ValueError as error:
                from worklogger.presentation.errors import display_error_code
                QMessageBox.warning(self, _("Place historical break"), display_error_code(str(error)))
                return
            if self._confirm_periods(_("Place historical break"), preview):
                self._submit(lambda: self.view_model.convert_break(record, minutes))

    def _confirm_periods(self, title, periods):
        lines = []
        for period in periods:
            start, end = (period.started_at, period.ended_at) if period.started_at else TimeRange(period.start_time, period.end_time).as_datetimes(period.day)
            lines.append(f"{start.isoformat(timespec='minutes')} - {end.isoformat(timespec='minutes')} [{work_type_label(period.work_type)}]")
        lines.append(_("Worked: {hours}").format(hours=duration_label(sum(period.worked_hours() for period in periods))))
        if len({period.day for period in periods}) > 1:
            lines.append(_("Splitting across dates changes daily and period totals."))
        return QMessageBox.question(self, title, _("Save these periods?") + "\n\n" + "\n".join(lines),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def _undo_record_change(self):
        if not self._changes_confirmed():
            return
        def ready(result):
            if not result.ok:
                self._apply_result(result, refresh=False)
                return
            change = result.value
            if change is None:
                QMessageBox.information(self, _("Undo latest record change"), _("No reversible record changes are available."))
                return
            entry = change.entry
            question = _("Undo the latest record change for {date}, {start} - {end}? This does not restart a timer.").format(
                date=day_label(entry.day), start=entry.start_time or "", end=entry.end_time or "")
            if change.operation == "associate":
                days = [record.day for record in change.entries]
                question = _("Undo project associations for {count} records from {start} to {end}?").format(
                    count=len(change.entries), start=min(days).isoformat(), end=max(days).isoformat())
            if QMessageBox.question(self, _("Undo latest record change"), question,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                self._submit(lambda: self.view_model.undo(change.id))
        self._submit(self.view_model.latest_change, refresh=False, on_complete=ready)

    def delete_event(self, event):
        if self.is_busy:
            return
        if QMessageBox.question(self, _("Delete record"), _("Delete this calendar event?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self._submit(lambda: self.view_model.delete_event(event))

    def discard_changes(self):
        self.view_model.discard_changes()
        self._render_editor()
