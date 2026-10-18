"""Automatic recording transitions, break handling and reminder presentation."""

from PySide6.QtCore import QTimer
from time import monotonic
from PySide6.QtWidgets import QMessageBox

from worklogger.config.constants import MAX_SHIFT_HOURS
from worklogger.domain.shared.errors import ConflictError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import EntryType, EntryCategory
from worklogger.infrastructure.i18n import _
from worklogger.presentation.date_labels import day_label, duration_label
from worklogger.presentation.widgets.end_timer import EndTimerDialog


class AutomaticRecordingActions:
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
            if self.view_model.editing_active_timer and self.time_tabs.currentIndex() == 0:
                self.selected_record_label.setText(status)

    def recording_action_state(self):
        state = self.view_model.editor_state(automatic=True)
        definition = self._classification_definition(state)
        can_start = (not self.is_busy and self.view_model.timer is None and not self.view_model.restore_failed
                     and definition.category in (EntryCategory.WORK, EntryCategory.BREAK)
                     and not (isinstance(definition, EntryType) and definition.is_legacy))
        can_end = not self.is_busy and self.view_model.timer is not None
        return can_start, can_end

    def start_recording(self):
        if self.recording_action_state()[0]:
            self._start_with_content(self.view_model.auto_entry_type, self.view_model.auto_content)

    def end_recording(self):
        if self.recording_action_state()[1]:
            self._finish()

    def _start(self):
        if self.recording_action_state()[0]:
            state = self.view_model.editor_state(automatic=True)
            self._start_with_content(state.entry_type, state.content)

    def _start_with_content(self, entry_type, content):
        self._polish_task.cancel()
        moment = self.view_model.now()
        self._submit(lambda model: model.start(entry_type, content, now=moment), refresh=False,
                     on_complete=lambda result: self._complete_start(result, entry_type, content, moment))

    def _complete_start(self, result, entry_type, content, moment):
        if result.error is None or result.error.code != "fixed_break_active":
            self._apply_result(result, refresh=False)
            return
        dialog = QMessageBox(QMessageBox.Icon.Question, _("End break early?"),
            _("End the break at {time} and start recording? The saved break duration will be shortened.").format(time=moment.strftime("%H:%M")),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        dialog.button(QMessageBox.StandardButton.Yes).setText(_("Start"))
        dialog.button(QMessageBox.StandardButton.No).setText(_("Cancel"))
        answer = dialog.exec()
        dialog.deleteLater()
        if answer == QMessageBox.StandardButton.Yes:
            record = result.error.details.get("break_entry")
            if record is None:
                self._apply_result(result, refresh=False)
                return
            self._submit(lambda model: model.start(entry_type, content, now=moment, break_entry=record))

    def _finish(self):
        self._polish_task.cancel()
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
                def finish_corrected(model):
                    current = model.timer
                    if current is None or current.capture_id != capture_id:
                        return Result.failure(ConflictError("time_entry_timer_conflict", "time_entry_timer_conflict"))
                    return model.finish(now=end)
                self._submit(finish_corrected)
            dialog.accepted.connect(accepted)
            dialog.finished.connect(lambda: setattr(self, "_end_dialog", None))
            dialog.finished.connect(dialog.deleteLater)
            dialog.open()
            return
        def finish(model):
            advanced = model.advance(now=moment)
            return model.finish(now=moment) if advanced.ok else advanced
        self._submit(finish)

    def _break(self):
        self._polish_task.cancel()
        if self.view_model.restore_failed:
            return
        moment = self.view_model.now()
        self._submit(lambda model: model.take_break(now=moment))

    def _tick(self):
        if self.is_busy:
            return
        if self.view_model.resume_due and monotonic() >= self._timer_retry_after:
            self._submit(lambda model: model.advance(), automatic=True)
        else:
            self._update_elapsed_label()

    def _discard_timer(self):
        if QMessageBox.question(self, _("Discard timer"), _("Discard the saved timer without creating a record?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self._submit(lambda model: model.discard_timer())
