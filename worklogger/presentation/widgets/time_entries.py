"""Compact editor for individually recorded work periods."""

from datetime import date
from time import monotonic

from PySide6.QtCore import QEvent, QTimer, Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSizePolicy, QStyle, QStyleOptionTabWidgetFrame,
    QTabWidget, QTextEdit, QToolButton, QVBoxLayout, QWidget, QStackedWidget)

from worklogger.domain.worklog.models import WorkLog, EntryType
from worklogger.domain.worklog.replacement import EntryReplacement
from worklogger.domain.worklog.rules import calc_shift_span_hours
from worklogger.domain.shared.errors import InfrastructureError, ValidationError
from worklogger.domain.shared.errors import CancellationError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import _
from worklogger.presentation.date_labels import duration_label, day_label
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.viewmodels.time_entries import TimeEntryViewModel
from worklogger.presentation.widgets.icons import set_button_icon, ui_icon
from worklogger.presentation.widgets.time_picker import TimePickerDialog
from worklogger.presentation.widgets.classification_picker import ClassificationButton, ClassificationPicker
from worklogger.presentation.entry_type_labels import classification_label
from worklogger.presentation.processing import TextProcessingTask
from worklogger.presentation.job_runner import owned_callback
from worklogger.presentation.widgets.processing_progress import ProcessingProgress
from worklogger.presentation.theme.widget_style import set_style_property


from worklogger.presentation.widgets.time_entry_actions import TimeEntryRecordActions
from worklogger.presentation.widgets.time_entry_recording import AutomaticRecordingActions


class TimeEntryPanel(QWidget, TimeEntryRecordActions, AutomaticRecordingActions):
    editor_layout_changed = Signal()
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
        self._ai_ready = view_model.rewrite_available
        self._polish_task = TextProcessingTask(self, job_runner=job_runner)
        self.is_busy = False
        self._updating = False
        self._timer_failed = False
        self._timer_retry_after = 0
        self._reminder_capture = None
        self._notified_reminders = set()
        self._end_dialog = None
        self._record_boundary_dialog = None
        self._replacement_dialog = None
        self._classification_popup = None
        self._classification_origin = None
        self._recent_context_visible = True
        self._day = view_model.draft.day
        self.setObjectName("worklog_entry_panel_widget")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setProperty("compact", compact)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
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
        self.selected_record_label = QLabel()
        self.selected_record_label.setProperty("role", "secondary")
        self.selected_record_label.setWordWrap(True)
        self.selected_record_label.hide()
        root.addWidget(self.selected_record_label)
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
            button.setProperty("variant", "primary")
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
        self.discard_timer_button.setProperty("variant", "danger")
        set_button_icon(self.discard_timer_button, "trash")
        self.discard_timer_button.clicked.connect(self._discard_timer)
        break_row.addWidget(self.discard_timer_button, 1)
        auto_layout.addLayout(break_row)
        self.auto_status_label = QLabel()
        self.auto_status_label.setObjectName("auto_status_label")
        self.auto_status_label.setWordWrap(True)
        auto_layout.addWidget(self.auto_status_label)
        self.time_tabs.addTab(auto, _("Auto Record"))

        self._custom_types = ()
        self._reload_entry_types()
        classification_column = QVBoxLayout()
        classification_column.setSpacing(2)
        classification_caption = QLabel(_("Classification"))
        self.classification_button = ClassificationButton(self)
        classification_caption.setBuddy(self.classification_button)
        classification_column.addWidget(classification_caption)
        classification_column.addWidget(self.classification_button)
        root.addLayout(classification_column)
        self.classification_button.clicked.connect(self._open_classification_picker)
        inventory = view_model.project_inventory()
        self._context_error = inventory.error
        self._project_inventory = inventory.value if inventory.ok else ((), {})
        recent = view_model.recent_contexts()
        self._recent_contexts = recent.value if recent.ok else ()
        self.content_heading = QWidget()
        self.content_heading.setObjectName("time_entry_content_heading_widget")
        content_heading = QHBoxLayout(self.content_heading)
        content_heading.setContentsMargins(0, 0, 0, 0)
        content_heading.addWidget(QLabel(_("Content")), 1)
        self.polish_button = QToolButton()
        self.polish_button.setObjectName("polish_time_entry_button")
        self.polish_button.setToolTip(_("Polish text"))
        self.polish_button.setAccessibleName(_("Polish text"))
        self.polish_button.setProperty("variant", "outline")
        set_button_icon(self.polish_button, "sparkles")
        self.polish_button.setFixedSize(28, 28)
        self.polish_button.clicked.connect(self._polish_content)
        content_heading.addWidget(self.polish_button)
        self.content_heading_stack = QStackedWidget()
        self.content_heading_stack.setObjectName("time_entry_content_heading_stack_widget")
        self.content_heading_stack.addWidget(self.content_heading)
        self.processing_progress = ProcessingProgress()
        self.processing_progress.bar.setFixedWidth(48)
        self.processing_progress.cancel_button.setFixedSize(28, 28)
        self.content_heading_stack.setFixedHeight(28)
        self.content_heading_stack.addWidget(self.processing_progress)
        self.content_heading_stack.setCurrentWidget(self.content_heading)
        self.processing_progress.cancel_requested.connect(self._polish_task.cancel)
        self._polish_task.started.connect(lambda: self.processing_progress.start(_("Polishing text...")))
        self._polish_task.started.connect(lambda: self.content_heading_stack.setCurrentWidget(self.processing_progress))
        self._polish_task.finished.connect(self.processing_progress.finish)
        self._polish_task.finished.connect(lambda: self.content_heading_stack.setCurrentWidget(self.content_heading))
        self._polish_task.started.connect(self.editor_layout_changed)
        self._polish_task.finished.connect(self.editor_layout_changed)
        content_column = QVBoxLayout()
        content_column.setContentsMargins(0, 0, 0, 0)
        content_column.setSpacing(3)
        content_column.addWidget(self.content_heading_stack)
        self.content_input = QTextEdit()
        self.content_input.setObjectName("time_entry_content_text_edit")
        self.content_input.setAcceptRichText(False)
        self.content_input.setFixedHeight(76)
        content_column.addWidget(self.content_input)
        root.addLayout(content_column)
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
        self.clear_button.setProperty("variant", "outline")
        set_button_icon(self.clear_button, "eraser")
        self.clear_button.setToolTip(_("Clear input"))
        self.clear_button.setAccessibleName(_("Clear input"))
        actions.addWidget(self.clear_button)
        self.undo_button = QToolButton(self.actions_widget)
        self.undo_button.setObjectName("undo_record_change_button")
        self.undo_button.setProperty("variant", "outline")
        set_button_icon(self.undo_button, "rotate-ccw")
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
        action.setText(title)
        action.setToolTip(title)
        action.triggered.connect(lambda: self._pick_time(field, title))
        return field

    def _reload_entry_types(self):
        result = self.view_model.list_entry_types()
        if result.ok:
            self._custom_types = result.value
        return result

    @property
    def recent_context_visible(self):
        return self._recent_context_visible

    def set_recent_context_visible(self, enabled):
        self._recent_context_visible = bool(enabled)
        self._close_classification_picker()

    def _classification_definition(self, state):
        if state.type_snapshot is not None and state.type_snapshot.value == state.entry_type:
            return state.type_snapshot
        definition = next((item for item in self._custom_types if item.value == state.entry_type), None)
        return definition if definition is not None else EntryType(state.entry_type)

    def _close_classification_picker(self):
        self._classification_origin = None
        if self._classification_popup is not None:
            self._classification_popup.hide()

    def _open_classification_picker(self):
        if self.is_busy or not self.classification_button.isEnabled():
            return
        automatic = self.time_tabs.currentIndex() == 1
        state = self.view_model.editor_state(automatic=automatic)
        if state.active_timer is not None:
            return
        self._classification_origin = (automatic, state)
        if self._classification_popup is None:
            self._classification_popup = ClassificationPicker(self, validator=self._validate_classification)
            self._classification_popup.selection_applied.connect(self._apply_classification)
        self._classification_popup.open_for(self.classification_button,
            definition=self._classification_definition(state), work_mode=state.work_mode,
            context=state.context, custom_types=self._custom_types, inventory=self._project_inventory,
            recent=self._recent_contexts, automatic=automatic,
            projects_available=self.view_model.projects_available, context_available=self._context_error is None,
            recent_context_visible=self.recent_context_visible)

    def _validate_classification(self, entry_type, work_mode, context):
        automatic = self.time_tabs.currentIndex() == 1
        state = self.view_model.editor_state(automatic=automatic)
        if (self.is_busy or not self.isEnabled() or self._classification_origin != (automatic, state)
                or state.active_timer is not None):
            self._close_classification_picker()
            return Result.failure(ValidationError("worklog_entry_conflict", "worklog_entry_conflict"))
        return self.view_model.validate_selection(entry_type, work_mode, context, automatic=automatic)

    def _apply_classification(self, selection):
        if self._classification_origin is None:
            return
        automatic, state = self._classification_origin
        definition, work_mode, context = selection
        if automatic:
            self.view_model.update_auto(content=state.content, entry_type=definition.value,
                context=context, work_mode=work_mode)
        else:
            self.view_model.update(start=state.draft.start, end=state.draft.end,
                content=state.content, entry_type=definition.value, context=context, work_mode=work_mode)
        self._render_editor()

    def refresh_entry_types(self):
        self._close_classification_picker()
        self._updating = True
        try:
            result = self._reload_entry_types()
        finally:
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
        self._close_classification_picker()
        def completed(result):
            if result.ok:
                self._context_error = None
                self._updating = True
                try:
                    self._project_inventory = result.value
                    recent = self.view_model.recent_contexts()
                    if recent.ok:
                        self._recent_contexts = recent.value
                finally:
                    self._updating = False
                self._render_editor()
            else:
                self._apply_result(result, refresh=False)
        self._submit(lambda model: model.project_inventory(), refresh=False, on_complete=completed)

    @property
    def is_dirty(self):
        return self.view_model.manual_dirty or self.view_model.auto_dirty

    def load_day(self, day: date):
        self._close_classification_picker()
        if self.is_busy:
            return Result.failure(InfrastructureError("worklog_entry_conflict", "worklog_entry_conflict"))
        if day != self._day:
            self._polish_task.cancel()
        self._day = day
        result = self.view_model.load(day)
        if result.ok:
            self._render_editor()
            self.hours_label.setText(_("Worked: {hours}").format(hours=duration_label(sum(entry.worked_hours() for entry in result.value))))
        return result

    def edit_entry(self, record: WorkLog):
        self._close_classification_picker()
        if self.is_busy:
            return
        if self.view_model.manual_dirty and not self._confirm_discard():
            self.selection_changed.emit(self.view_model.draft.original.id if self.view_model.draft.original else None)
            return
        loaded = self.view_model.get_entry(record.id)
        if not loaded.ok:
            self._apply_result(loaded, refresh=False)
            return
        self._polish_task.cancel()
        self.view_model.select(loaded.value)
        self.time_tabs.setCurrentIndex(0)
        self._render_editor()
        self.start_input.setFocus()

    def copy_event(self, event):
        self._close_classification_picker()
        if self.is_busy or self.view_model.manual_dirty and not self._confirm_discard():
            return
        self._polish_task.cancel()
        self.view_model.new(event.day)
        self.time_tabs.setCurrentIndex(0)
        start, end = event.start_time or "", "00:00" if event.end_time == "24:00" else event.end_time or ""
        if start and end and calc_shift_span_hours(start, end) is None:
            start, end = "", ""
        self.view_model.update(start=start, end=end, entry_type="meeting", work_mode=None,
                               content="\n".join(part for part in (event.summary, event.description, event.location) if part))
        self._render_editor()

    def _mode_changed(self, *_args):
        self._close_classification_picker()
        if self._polish_task.is_running and self._processing_target() != self._polish_target:
            self._polish_task.cancel()
        self._render_editor()

    def _processing_target(self):
        return self.view_model.editor_state(automatic=self.time_tabs.currentIndex() == 1).processing_target

    def _draft_changed(self, *_args):
        if self._updating:
            return
        self._close_classification_picker()
        state = self.view_model.editor_state(automatic=self.time_tabs.currentIndex() == 1)
        if self.time_tabs.currentIndex() == 0:
            self.view_model.update(start=self.start_input.text(), end=self.end_input.text(),
                                   entry_type=state.entry_type, content=self.content_input.toPlainText(),
                                   context=state.context)
        else:
            self.view_model.update_auto(content=self.content_input.toPlainText(),
                entry_type=state.entry_type, context=state.context)
        self._update_actions()
        self.dirty_changed.emit(self.is_dirty)

    def _render_editor(self):
        self._close_classification_picker()
        self._updating = True
        try:
            auto = self.time_tabs.currentIndex() == 1
            state = self.view_model.editor_state(automatic=auto)
            variant = "outline" if auto else "primary"
            set_style_property(self.save_button, "variant", variant)
            draft = state.draft
            linked_timer = state.linked_timer
            self.start_input.setText(draft.start)
            self.end_input.setText(draft.end)
            definition = self._classification_definition(state)
            self.classification_button.set_summary(classification_label(definition, state.work_mode),
                state.context.label if definition.category == "work" else "")
            content = state.content
            if self.content_input.toPlainText() != content:
                self.content_input.setPlainText(content)
            selected = state.selected_record
            self.selected_record_label.setText(_("Editing record: {date} {start} - {end}").format(
                date=day_label(selected.day), start=selected.start_time or "", end=selected.end_time or "") if selected else "")
            self.selected_record_label.setVisible(selected is not None)
            if linked_timer and not auto:
                timer = self.view_model.timer
                self.selected_record_label.setText(_("Recording since {time} - {duration}").format(
                    time=f"{day_label(timer.started_at.date())} {timer.started_at:%H:%M}", duration=duration_label(self.view_model.elapsed_hours())))
                self.selected_record_label.show()
            self.start_input.setReadOnly(linked_timer)
            self.end_input.setReadOnly(linked_timer)
            self.start_input.setEnabled(not linked_timer)
            self.end_input.setEnabled(not linked_timer)
            self.classification_button.setEnabled(state.active_timer is None)
            legacy = state.historical_break_hours
            self.history_label.setText(_("Historical break deduction: {hours}").format(hours=duration_label(legacy)) if legacy else "")
            if self._context_error is not None:
                self.history_label.setText(display_error_message(self._context_error))
            self.history_label.setVisible(bool(legacy) or self._context_error is not None)
        finally:
            self._updating = False
        self._update_actions()
        selected = state.selected_record
        self._fit_mode_height()
        self.selection_changed.emit(selected.id if selected else None)
        self.dirty_changed.emit(self.is_dirty)
        self.editor_layout_changed.emit()

    def _update_actions(self):
        rewriting = self._polish_task.is_running
        ready = False if rewriting else self._ai_ready
        self.polish_button.setEnabled(not self.is_busy and not rewriting and ready and bool(self.content_input.toPlainText().strip()))
        self.polish_button.setToolTip(_("Polish text") if ready or rewriting else _("Text processing is not ready. Check AI settings."))
        self.content_input.setReadOnly(rewriting)
        state = self.view_model.editor_state(automatic=self.time_tabs.currentIndex() == 1)
        timer = self.view_model.timer
        self.undo_button.setEnabled(not self.is_busy and timer is None and not self.view_model.restore_failed
                                    and self.view_model.latest_change_info is not None)
        tick = getattr(self, "auto_timer", None)
        if tick is not None:
            if timer and not self.is_busy and not tick.isActive():
                tick.start()
            elif not timer and tick.isActive():
                tick.stop()
        self.clock_in_button.setEnabled(self.recording_action_state()[0])
        self.clock_out_button.setEnabled(timer is not None)
        self.discard_timer_button.setEnabled(timer is not None or self.view_model.restore_failed)
        self.break_button.setText(_("Break {hours}").format(hours=duration_label(self.view_model.default_break_hours)))
        self.break_button.setEnabled(timer is None and not self.view_model.restore_failed and self.view_model.default_break_hours > 0)
        captions = {"new": _("Save"), "changes": _("Save changes"), "content": _("Save content")}
        self.save_button.setText(captions[state.save_action])
        self.save_button.setEnabled(state.can_save and not rewriting)
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





    def eventFilter(self, watched, event):
        if watched is self.time_tabs and event.type() in (QEvent.Type.Resize, QEvent.Type.LayoutRequest, QEvent.Type.StyleChange, QEvent.Type.FontChange):
            if not self._mode_height_pending:
                self._mode_height_pending = True
                QTimer.singleShot(0, self, self._fit_mode_height)
        return super().eventFilter(watched, event)

    def hideEvent(self, event):
        self._close_classification_picker()
        super().hideEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.EnabledChange, QEvent.Type.StyleChange, QEvent.Type.LanguageChange):
            self._close_classification_picker()
        if event.type() == QEvent.Type.LanguageChange and self._classification_popup is not None:
            self._classification_popup.deleteLater()
            self._classification_popup = None

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
            self.layout().invalidate()
            self.updateGeometry()
            parent = self.parentWidget()
            if parent is not None and parent.layout() is not None:
                parent.layout().invalidate()
                parent.layout().activate()
            self.layout().activate()

    def _apply_result(self, result, *, refresh=True):
        self._close_classification_picker()
        if not result.ok:
            plan = result.error.details.get("replacement")
            if isinstance(plan, EntryReplacement):
                self._offer_replacement(plan)
                return False
            QMessageBox.warning(self, _("WorkLogger"), display_error_message(result.error))
            return False
        self._timer_failed = False
        recent = self.view_model.recent_contexts()
        if recent.ok:
            self._recent_contexts = recent.value
        self._render_editor()
        if refresh:
            record = result.value
            timer = self.view_model.timer
            day = record.day if isinstance(record, WorkLog) else timer.started_at.date() if timer else self._day
            self.records_changed.emit(day)
        return True

    def _submit(self, operation, *, refresh=True, automatic=False, on_complete=None):
        self._close_classification_picker()
        if self.is_busy:
            return
        self._polish_task.cancel()
        work = self.view_model.prepare_operation(operation)
        if self._job_runner is None:
            result = self.view_model.apply_operation_result(work().value)
            if on_complete is None:
                self._apply_result(result, refresh=refresh)
            else:
                on_complete(result)
            self._update_actions()
            return
        self.is_busy = True
        self.auto_timer.stop()
        self.setEnabled(False)
        self.busy_changed.emit(True)

        def complete(result):
            if result.ok:
                result = self.view_model.apply_operation_result(result.value)
            self.is_busy = False
            self.setEnabled(True)
            self.busy_changed.emit(False)
            repeated_failure = automatic and not result.ok and self._timer_failed
            if automatic and not result.ok:
                self._timer_failed = True
                self._timer_retry_after = monotonic() + 5
            try:
                if on_complete is None:
                    if not repeated_failure:
                        self._apply_result(result, refresh=refresh and (not automatic or result.value is not None))
                else:
                    on_complete(result)
            finally:
                self._update_actions()

        try:
            self._job_runner.submit("time_entry_update", lambda _token: work(),
                                    on_complete=owned_callback(self, complete))
        except Exception:
            self.is_busy = False
            self.setEnabled(True)
            self.busy_changed.emit(False)
            self._update_actions()
            self._apply_result(Result.failure(InfrastructureError("worklog_save_failed", "worklog_save_failed")), refresh=False)

    def _save(self):
        content_only = self.time_tabs.currentIndex() == 1 or self.view_model.editing_active_timer
        self._submit(lambda model: model.save_content() if content_only else model.save_manual())

    def _polish_content(self):
        if self.is_busy or self._polish_task.is_running:
            return
        content = self.content_input.toPlainText()
        if not content.strip():
            return
        self._polish_target = self._processing_target()
        def complete(result):
            if result.ok:
                self.content_input.setPlainText(result.value)
            elif not isinstance(result.error, CancellationError):
                self._apply_result(result, refresh=False)
            if not isinstance(result.error, CancellationError):
                self._ai_ready = self.view_model.rewrite_available
            self._update_actions()
        self._polish_task.run("polish_record_content", lambda token: self.view_model.rewrite_content(content, cancellation_token=token), on_complete=complete)
        self._update_actions()



    def refresh_ai_availability(self):
        self._ai_ready = self.view_model.rewrite_available
        self._update_actions()





    def _clear(self):
        self._polish_task.cancel()
        if self.time_tabs.currentIndex() == 1 and self.view_model.timer is not None:
            self.view_model.auto_content = ""
        else:
            self.view_model.clear(self._day)
        self._render_editor()

    def new_record(self):
        self._polish_task.cancel()
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


    def delete_entry(self, record: WorkLog):
        if self.is_busy:
            return
        if QMessageBox.question(self, _("Delete record"), _("Delete this time record?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self._submit(lambda model: model.delete_entry(record))








    def delete_event(self, event):
        if self.is_busy:
            return
        if QMessageBox.question(self, _("Delete record"), _("Delete this calendar event?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self._submit(lambda model: model.delete_event(event))

    def discard_changes(self):
        self._polish_task.cancel()
        self.view_model.discard_changes()
        self._render_editor()
