"""Record transformations and undo prompts shared by recording panels."""

import math

from PySide6.QtWidgets import QInputDialog, QMenu, QMessageBox

from worklogger.domain.worklog.editing import place_historical_break, split_entry
from worklogger.domain.worklog.models import TimeRange
from worklogger.infrastructure.i18n import _
from worklogger.presentation.date_labels import day_label, duration_label
from worklogger.presentation.widgets.icons import ui_icon
from worklogger.presentation.work_type_labels import work_type_label


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
