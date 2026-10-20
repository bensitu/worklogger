"""Shared period and imported-event list for calendar and compact windows."""

from PySide6.QtCore import QEvent, Signal
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
from worklogger.infrastructure.i18n import _, get_language
from worklogger.presentation.date_labels import duration_label
from worklogger.presentation.entry_type_labels import classification_label
from worklogger.presentation.widgets.record_summary import RecordSummaryButton


class TimeEntryHistory(QWidget):
    entry_selected = Signal(object)
    entry_delete_requested = Signal(object)
    event_selected = Signal(object)
    event_delete_requested = Signal(object)
    entry_actions_requested = Signal(object, object)

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
        self._rendered_content = None
        self._empty_label = QLabel(_("No records for the selected day."), self)
        self._empty_label.setWordWrap(True)
        self._empty_label.hide()

    def showEvent(self, event):
        super().showEvent(event)
        QApplication.instance().installEventFilter(self)

    def hideEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        super().hideEvent(event)

    def set_entries(self, entries, events=()):
        entries, events = tuple(entries), tuple(events)
        selected = self.view_model.draft.original
        content = (entries, events, get_language(), bool(getattr(self.view_model, "changes_available", False)),
                   self.view_model.events_deletable)
        if content == self._rendered_content:
            self.set_selected_entry(selected.id if selected else None)
            return
        self._rendered_content = content
        self._hovered = None
        old_entries, old_events = self.entry_buttons, self.event_buttons
        self.entry_buttons = {}
        self.event_buttons = {}
        while self.rows.count():
            self.rows.takeAt(0)
        self._empty_label.hide()
        for entry in entries:
            first_line = entry.note.splitlines()[0] if entry.note else ""
            content = first_line[:64] + ("..." if len(first_line) > 64 else "")
            span = f"{entry.start_time} - {entry.end_time}" if entry.has_times else _("All day")
            classification = classification_label(entry.entry_type, entry.work_mode)
            text = f"{span}  {duration_label(entry.raw_hours())}\n{classification}"
            if entry.context.label:
                text += "\n" + entry.context.label
            if content:
                text += "\n" + content
            button = old_entries.pop(entry.id, None)
            if button is None:
                button = self._button(text, actions_enabled=content[3])
                button.actions_requested.connect(lambda position, button=button: self.entry_actions_requested.emit(button.property("record"), position))
                button.clicked.connect(lambda _checked=False, button=button: self.entry_selected.emit(button.property("record")))
                button.delete_requested.connect(lambda button=button: self.entry_delete_requested.emit(button.property("record")))
            button.setProperty("record", entry)
            button.label.setText(text)
            self.rows.addWidget(button)
            button.setProperty("entry_id", entry.id)
            self.entry_buttons[entry.id] = button
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setChecked(bool(selected and selected.id == entry.id))
            button.setToolTip("\n".join(value for value in (classification, entry.context.label, entry.note) if value))
            button.setAccessibleName(_("Edit record") + ": " + text)
        for event in events:
            span = _("All day") if event.all_day else f"{event.start_time or '--:--'} - {event.end_time or '--:--'}"
            text = f"{span}\n{_('Calendar event')}\n{event.summary}"
            button = old_events.pop(event.id, None)
            if button is None:
                button = self._button(text, deletable=self.view_model.events_deletable)
                button.clicked.connect(lambda _checked=False, button=button: self.event_selected.emit(button.property("record")))
                button.delete_requested.connect(lambda button=button: self.event_delete_requested.emit(button.property("record")))
            button.setProperty("record", event)
            button.label.setText(text)
            self.rows.addWidget(button)
            button.setToolTip(_("Create record from event"))
            self.event_buttons[event.id] = button
            button.setAccessibleName(_("Create record from event") + ": " + event.summary)
        for button in (*old_entries.values(), *old_events.values()):
            button.setAutoExclusive(False)
            button.hide()
            button.deleteLater()
        if not entries and not events:
            self._empty_label.setText(_("No records for the selected day."))
            self.rows.addWidget(self._empty_label)
            self._empty_label.show()
        self.rows.addStretch(1)

    def _button(self, text, *, deletable=True, actions_enabled=False):
        button = RecordSummaryButton(text, deletable=deletable, actions_enabled=actions_enabled)
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
