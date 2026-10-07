"""Shared period and imported-event list for calendar and compact windows."""

from PySide6.QtCore import QEvent, Signal
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
from worklogger.infrastructure.i18n import _
from worklogger.presentation.date_labels import duration_label
from worklogger.presentation.work_type_labels import work_type_label
from worklogger.presentation.widgets.record_summary import RecordSummaryButton


class TimeEntryHistory(QWidget):
    entry_selected = Signal(object)
    entry_delete_requested = Signal(object)
    event_selected = Signal(object)
    event_delete_requested = Signal(object)

    def __init__(self, view_model, parent=None):
        super().__init__(parent)
        self.view_model = view_model
        self.setObjectName("calendar_records_widget")
        self.rows = QVBoxLayout(self)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(4)
        self._hovered = None
        self.entry_buttons = {}
        self.event_buttons = {}

    def showEvent(self, event):
        super().showEvent(event)
        QApplication.instance().installEventFilter(self)

    def hideEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        super().hideEvent(event)

    def set_entries(self, entries, events=()):
        self._hovered = None
        self.entry_buttons = {}
        self.event_buttons = {}
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget() is not None:
                if isinstance(item.widget(), RecordSummaryButton):
                    item.widget().setAutoExclusive(False)
                    item.widget().setChecked(False)
                item.widget().hide()
                item.widget().deleteLater()
        selected = self.view_model.draft.original
        for entry in entries:
            first_line = entry.note.splitlines()[0] if entry.note else ""
            content = first_line[:64] + ("..." if len(first_line) > 64 else "")
            span = f"{entry.start_time} - {entry.end_time}" if entry.has_times else _("All day")
            text = f"{span}  {duration_label(entry.raw_hours())}\n{work_type_label(entry.work_type)}"
            if content:
                text += "\n" + content
            button = self._button(text)
            button.setProperty("entry_id", entry.id)
            self.entry_buttons[entry.id] = button
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setChecked(bool(selected and selected.id == entry.id))
            button.setToolTip(entry.note or work_type_label(entry.work_type))
            button.setAccessibleName(_("Edit record") + ": " + text)
            button.clicked.connect(lambda _checked=False, entry=entry: self.entry_selected.emit(entry))
            button.delete_requested.connect(lambda entry=entry: self.entry_delete_requested.emit(entry))
        for event in events:
            span = _("All day") if event.all_day else f"{event.start_time or '--:--'} - {event.end_time or '--:--'}"
            button = self._button(f"{span}\n{_('Calendar event')}\n{event.summary}",
                                  deletable=self.view_model.service.calendar_events is not None)
            button.setToolTip(_("Create record from event"))
            self.event_buttons[event.id] = button
            button.setAccessibleName(_("Create record from event") + ": " + event.summary)
            button.clicked.connect(lambda _checked=False, event=event: self.event_selected.emit(event))
            button.delete_requested.connect(lambda event=event: self.event_delete_requested.emit(event))
        if not entries and not events:
            empty = QLabel(_("No records for the selected day."))
            empty.setWordWrap(True)
            self.rows.addWidget(empty)
        self.rows.addStretch(1)

    def _button(self, text, *, deletable=True):
        button = RecordSummaryButton(text, deletable=deletable)
        button.hovered.connect(lambda hovered: setattr(self, "_hovered", hovered))
        self.rows.addWidget(button)
        return button

    def set_selected_entry(self, entry_id):
        for button in self.entry_buttons.values():
            button.setAutoExclusive(False)
            button.setChecked(button.property("entry_id") == entry_id)
            button.setAutoExclusive(True)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseMove and self.isVisible() and self._hovered is not None:
            position = event.globalPosition().toPoint()
            self._hovered.update_delete_visibility(position)
            if not self._hovered.rect().contains(self._hovered.mapFromGlobal(position)):
                self._hovered = None
        return super().eventFilter(watched, event)
