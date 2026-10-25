"""Record transformations and undo prompts shared by recording panels."""

from PySide6.QtWidgets import QMenu, QMessageBox
from worklogger.infrastructure.i18n import _
from worklogger.presentation.date_labels import day_label
from worklogger.presentation.widgets.icons import ui_icon
from worklogger.presentation.widgets.record_edit_dialogs import RecordBoundaryDialog, OverlapReplacementDialog
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result


class TimeEntryRecordActions:
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
        self._open_boundary_dialog(record)

    def _open_boundary_dialog(self, record, *, historical_break=False):
        if not self._changes_confirmed() or self._record_boundary_dialog is not None:
            return
        try:
            dialog = RecordBoundaryDialog(record, self, zone=self.view_model.now().tzinfo, historical_break=historical_break)
        except ValueError:
            self._apply_result(Result.failure(ValidationError("record_split_invalid", "record_split_invalid")), refresh=False)
            return
        self._record_boundary_dialog = dialog
        def accepted():
            if historical_break:
                minutes = dialog.chosen_minutes()
                self._submit(lambda model: model.convert_break(record, minutes))
            else:
                boundary = dialog.chosen_boundary()
                self._submit(lambda model: model.split_at(record, boundary))
        dialog.accepted.connect(accepted)
        dialog.finished.connect(lambda: setattr(self, "_record_boundary_dialog", None))
        dialog.finished.connect(dialog.deleteLater)
        dialog.open()

    def _offer_replacement(self, plan):
        if self._replacement_dialog is not None:
            self._replacement_dialog.raise_()
            return
        try:
            dialog = OverlapReplacementDialog(plan, self)
        except ValueError:
            self._apply_result(Result.failure(ValidationError("time_range_invalid", "time_range_invalid")), refresh=False)
            return
        self._replacement_dialog = dialog
        def accepted():
            keep_outside = dialog.keep_outside
            self._submit(lambda model: model.replace_overlap(plan, keep_outside=keep_outside))
        dialog.accepted.connect(accepted)
        dialog.finished.connect(lambda: setattr(self, "_replacement_dialog", None))
        dialog.finished.connect(dialog.deleteLater)
        dialog.open()

    def _merge_record(self, previous, record):
        if previous is not None and self._changes_confirmed() and QMessageBox.question(self, _("Merge records"),
                _("Merge these adjacent records? Their content will be combined."), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self._submit(lambda model: model.merge(previous, record))

    def _place_break(self, record):
        self._open_boundary_dialog(record, historical_break=True)

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
            elif change.operation == "replace":
                question = _("Undo the replacement and restore the previous records?")
            if QMessageBox.question(self, _("Undo latest record change"), question,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                self._submit(lambda model: model.undo(change.id))
        self._submit(lambda model: model.latest_change(), refresh=False, on_complete=ready)
