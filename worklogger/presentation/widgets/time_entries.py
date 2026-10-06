"""Compact editor for individually recorded work periods."""

from datetime import date

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSizePolicy, QStyle, QStyleOptionTabWidgetFrame,
    QTabWidget, QTextEdit, QToolButton, QVBoxLayout, QWidget)

from worklogger.domain.worklog.models import WorkLog, WorkType
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.rules import timestamp_span_hours
from worklogger.infrastructure.i18n import _
from worklogger.presentation.date_labels import duration_label, day_label
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.viewmodels.time_entries import TimeEntryViewModel
from worklogger.presentation.widgets.icons import set_button_icon, ui_icon
from worklogger.presentation.widgets.worklog_entry import _TimePickerDialog
from worklogger.presentation.work_type_labels import work_type_label


class TimeEntryPanel(QWidget):
    records_changed = Signal(object)
    dirty_changed = Signal(bool)
    busy_changed = Signal(bool)
    selection_changed = Signal(object)

    def __init__(self, view_model: TimeEntryViewModel, *, compact: bool = True, parent=None, job_runner=None):
        super().__init__(parent)
        self.view_model = view_model
        self._job_runner = job_runner
        self.is_busy = False
        self._updating = False
        self._timer_failed = False
        self._day = view_model.draft.day
        self.setObjectName("worklog_entry_panel_widget")
        self.setProperty("compact", compact)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        self.time_tabs = QTabWidget()
        self.time_tabs.setObjectName("worklog_mode_tab_widget")
        self.time_tabs.setDocumentMode(True)
        self.time_tabs.tabBar().setObjectName("worklog_mode_selector_widget")
        self.time_tabs.tabBar().setExpanding(True)
        self.time_tabs.tabBar().setDrawBase(False)
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
        for work_type in (WorkType.NORMAL, WorkType.REMOTE, WorkType.BUSINESS_TRIP,
                          WorkType.MEETING, WorkType.TRAINING, WorkType.BREAK,
                          WorkType.PAID_LEAVE, WorkType.COMP_LEAVE, WorkType.SICK_LEAVE, WorkType.OTHER):
            self.work_type_combo.addItem(work_type_label(work_type), work_type.value)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setVerticalSpacing(3)
        form.addRow(_("Work type"), self.work_type_combo)
        root.addLayout(form)
        root.addWidget(QLabel(_("Content")))
        self.content_input = QTextEdit()
        self.content_input.setObjectName("time_entry_content_text_edit")
        self.content_input.setAcceptRichText(False)
        self.content_input.setFixedHeight(76)
        root.addWidget(self.content_input)
        self.hours_label = QLabel()
        self.hours_label.setObjectName("worklog_hours_label")
        root.addWidget(self.hours_label)
        actions = QHBoxLayout()
        self.save_button = QPushButton(_("Save"))
        self.save_button.setObjectName("save_worklog_button")
        self.save_button.setProperty("variant", "primary")
        set_button_icon(self.save_button, "save")
        actions.addWidget(self.save_button, 1)
        self.clear_button = QToolButton()
        self.clear_button.setObjectName("clear_time_entry_button")
        self.clear_button.setIcon(ui_icon("rotate-ccw"))
        self.clear_button.setToolTip(_("Clear input"))
        self.clear_button.setAccessibleName(_("Clear input"))
        actions.addWidget(self.clear_button)
        root.addLayout(actions)
        self.history_label = QLabel()
        self.history_label.setObjectName("time_entry_history_label")
        self.history_label.setProperty("role", "secondary")
        self.history_label.setWordWrap(True)
        root.addWidget(self.history_label)

        self.time_tabs.currentChanged.connect(self._mode_changed)
        for field in (self.start_input, self.end_input):
            field.textChanged.connect(self._draft_changed)
        self.work_type_combo.currentIndexChanged.connect(self._draft_changed)
        self.content_input.textChanged.connect(self._draft_changed)
        self.clock_in_button.clicked.connect(self._start)
        self.clock_out_button.clicked.connect(self._finish)
        self.break_button.clicked.connect(self._break)
        self.save_button.clicked.connect(self._save)
        self.clear_button.clicked.connect(self._clear)
        self.auto_timer = QTimer(self)
        self.auto_timer.setInterval(1000)
        self.auto_timer.timeout.connect(self._tick)
        if self.view_model.service.timer is not None:
            self.time_tabs.setCurrentIndex(1)
        self._render_editor()

    def _time_input(self, name, title):
        field = QLineEdit()
        field.setObjectName(name)
        field.setMinimumWidth(0)
        field.setPlaceholderText("HH:mm")
        action = field.addAction(ui_icon("clock"), QLineEdit.ActionPosition.TrailingPosition)
        action.setToolTip(title)
        action.triggered.connect(lambda: self._pick_time(field, title))
        return field

    def _pick_time(self, field, title):
        dialog = _TimePickerDialog(title, field.text(), self)
        dialog.accepted.connect(lambda: field.setText(dialog.time_input.time().toString("HH:mm")))
        dialog.open()

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
        loaded = self.view_model.service.get_entry(record.id)
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
        self.view_model.update(start=event.start_time or "", end=event.end_time or "", work_type="meeting",
                               content="\n".join(part for part in (event.summary, event.description, event.location) if part))
        self._render_editor()

    def _mode_changed(self, *_args):
        self._render_editor()

    def _draft_changed(self, *_args):
        if self._updating:
            return
        if self.time_tabs.currentIndex() == 0:
            self.view_model.update(start=self.start_input.text(), end=self.end_input.text(),
                                   work_type=str(self.work_type_combo.currentData()), content=self.content_input.toPlainText())
        else:
            self.view_model.auto_content = self.content_input.toPlainText()
            if self.view_model.service.timer is None:
                self.view_model.auto_work_type = str(self.work_type_combo.currentData())
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
            self.work_type_combo.setCurrentIndex(max(0, self.work_type_combo.findData(work_type)))
            self.content_input.setPlainText(self.view_model.auto_content if auto else draft.content)
            self.work_type_combo.setEnabled(not (auto and self.view_model.service.timer))
            legacy = draft.original.break_hours if not auto and draft.original else 0
            self.history_label.setText(_("Historical break deduction: {hours}").format(hours=duration_label(legacy)) if legacy else "")
            self.history_label.setVisible(bool(legacy))
        finally:
            self._updating = False
        self._update_actions()
        self.selection_changed.emit(self.view_model.draft.original.id if not auto and self.view_model.draft.original else None)
        self.dirty_changed.emit(self.is_dirty)

    def _update_actions(self):
        auto = self.time_tabs.currentIndex() == 1
        timer = self.view_model.service.timer
        tick = getattr(self, "auto_timer", None)
        if tick is not None:
            if timer and not self._timer_failed and not tick.isActive():
                tick.start()
            elif not timer and tick.isActive():
                tick.stop()
        self.clock_in_button.setEnabled(timer is None and not self.view_model.service.restore_failed)
        self.clock_out_button.setEnabled(timer is not None)
        self.discard_timer_button.setEnabled(timer is not None or self.view_model.service.restore_failed)
        self.break_button.setText(_("Resume work") if timer and timer.break_until else _("Break {hours}").format(hours=duration_label(self.view_model.default_break_hours)))
        self.break_button.setEnabled(bool(timer and (timer.break_until or timer.work_type != WorkType.BREAK and self.view_model.default_break_hours > 0)))
        self.save_button.setText(_("Save content") if auto else _("Save changes") if self.view_model.draft.original else _("Save"))
        self.save_button.setEnabled(self.view_model.auto_dirty and bool(timer or self.view_model.auto_completed) if auto else self.view_model.manual_dirty)
        if timer and timer.pending_end:
            self.clock_out_button.setText(_("Save"))
            self.break_button.setEnabled(False)
            self.auto_status_label.setText(_("Unsaved changes") + f": {timer.started_at:%H:%M} - {timer.pending_end:%H:%M}")
            self.auto_status_label.show()
        elif timer:
            self.clock_out_button.setText(_("End"))
            elapsed = max(0, timestamp_span_hours(timer.started_at, self.view_model.service.now()))
            self.auto_status_label.setText(_("Recording since {time} - {duration}").format(
                time=f"{day_label(timer.started_at.date())} {timer.started_at:%H:%M}", duration=duration_label(elapsed)))
            self.auto_status_label.show()
        else:
            self.auto_status_label.clear()
            self.auto_status_label.hide()
        if self.view_model.service.restore_failed:
            self.auto_status_label.setText(_("Unable to restore the timer. Discard it to start a new record."))
            self.auto_status_label.show()
            self.break_button.setEnabled(False)
        option = QStyleOptionTabWidgetFrame()
        self.time_tabs.initStyleOption(option)
        content = self.time_tabs.style().subElementRect(QStyle.SubElement.SE_TabWidgetTabContents, option, self.time_tabs)
        page = self.time_tabs.currentWidget()
        page.ensurePolished()
        page.layout().invalidate()
        page_height = max(page.sizeHint().height(), page.layout().totalHeightForWidth(max(1, content.width())))
        self.time_tabs.setFixedHeight(page_height + max(0, self.time_tabs.height() - content.height()))

    def _apply_result(self, result, *, refresh=True):
        if not result.ok:
            QMessageBox.warning(self, _("WorkLogger"), display_error_message(result.error))
            return False
        self._timer_failed = False
        self._render_editor()
        if refresh:
            record = result.value
            day = record.day if isinstance(record, WorkLog) else self._day
            self.records_changed.emit(day)
        return True

    def _submit(self, operation, *, refresh=True, automatic=False):
        if self.is_busy:
            return
        if self._job_runner is None:
            self._apply_result(operation(), refresh=refresh)
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
            self._apply_result(result, refresh=refresh and (not automatic or result.value is not None))

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

    def _start(self):
        work_type, content = str(self.work_type_combo.currentData()), self.content_input.toPlainText()
        moment = self.view_model.service.now()
        self._submit(lambda: self.view_model.start(work_type, content, now=moment), refresh=False)

    def _finish(self):
        moment = self.view_model.service.now()
        def finish():
            advanced = self.view_model.advance(now=moment)
            return self.view_model.finish(now=moment) if advanced.ok else advanced
        self._submit(finish)

    def _break(self):
        if self.view_model.service.restore_failed:
            return
        moment = self.view_model.service.now()
        self._submit(lambda: self.view_model.take_break(now=moment))

    def _tick(self):
        if self.is_busy:
            return
        timer = self.view_model.service.timer
        if timer and timer.break_until and self.view_model.service.now() >= timer.break_until:
            self._submit(self.view_model.advance, automatic=True)
        else:
            self._update_actions()

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
            def discard():
                result = self.view_model.service.discard_timer()
                if result.ok:
                    self.view_model.auto_content = ""
                    self.view_model.auto_completed = None
                return result
            self._submit(discard)

    def delete_entry(self, record: WorkLog):
        if self.is_busy:
            return
        if QMessageBox.question(self, _("Delete record"), _("Delete this time record?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            def delete():
                result = self.view_model.service.delete(record)
                if result.ok:
                    if self.view_model.draft.original and self.view_model.draft.original.id == record.id:
                        self.view_model.clear(self._day)
                    if self.view_model.auto_completed and self.view_model.auto_completed.id == record.id:
                        self.view_model.auto_completed = None
                        self.view_model.auto_content = ""
                return result
            self._submit(delete)

    def delete_event(self, event):
        if self.is_busy:
            return
        if QMessageBox.question(self, _("Delete record"), _("Delete this calendar event?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self._submit(lambda: self.view_model.service.delete_event(event))

    def discard_changes(self):
        self.view_model.discard_changes()
        self._render_editor()
