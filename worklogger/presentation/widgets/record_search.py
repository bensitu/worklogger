"""Debounced, paged record search that preserves keyboard focus and draft editing."""

from PySide6.QtCore import Qt, QTimer, Signal, QSignalBlocker
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout)
from shiboken6 import isValid

from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import EntryType, EntryCategory
from worklogger.domain.worklog.search import EntryFilter
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_code, display_error_message
from worklogger.presentation.widgets.assets import apply_window_icon
from worklogger.presentation.widgets.icons import set_button_icon, ui_icon
from worklogger.presentation.widgets.entry_type_options import add_entry_type_option
from worklogger.presentation.widgets.date_range import DateRangeControls
from worklogger.presentation.entry_type_labels import classification_label
from worklogger.presentation.date_labels import duration_label
from worklogger.presentation.widgets.data_tree import configure_data_tree, set_data_tooltips


_UNLINKED_PROJECT = "unlinked_project"


class RecordSearchDialog(QDialog):
    entry_selected = Signal(object)
    records_changed = Signal()

    def __init__(self, view_model, selected_day, parent=None, *, job_runner=None, selection_handler=None, criteria=None):
        super().__init__(parent)
        self._model, self._runner = view_model, job_runner
        self._selection_handler = selection_handler
        self._fixed_criteria = criteria
        self._cursor = None
        self._version = 0
        self._job = None
        self._loading = False
        self._items, self._projects = {}, ()
        self.setObjectName("record_search_dialog")
        self.setWindowTitle(_("Search records"))
        apply_window_icon(self)
        self.resize(960, 600)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        root.setSpacing(10)
        self.search_input = QLineEdit()
        self.search_input.setObjectName("record_search_line_edit")
        self.search_input.setPlaceholderText(_("Search records"))
        self.search_input.setAccessibleName(_("Search records"))
        self.search_input.setClearButtonEnabled(True)
        search_action = self.search_input.addAction(ui_icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        search_action.setToolTip(_("Search records"))
        search_action.triggered.connect(lambda _checked: self.search_input.setFocus())
        self.search_input.setMaxLength(512)
        root.addWidget(self.search_input)
        self.date_range = DateRangeControls(selected_day, horizontal=True)
        self.start_input, self.end_input = self.date_range.start_input, self.date_range.end_input
        root.addWidget(self.date_range)
        filters = QHBoxLayout()
        self.type_combo = QComboBox()
        self.project_combo = QComboBox()
        self.item_combo = QComboBox()
        self.type_combo.addItem(_("All entry types"), None)
        for value in EntryType:
            add_entry_type_option(self.type_combo, value)
        types = view_model.list_entry_types()
        if types.ok:
            for value in types.value:
                add_entry_type_option(self.type_combo, value)
        self.project_combo.addItem(_("All projects"), None)
        self.project_combo.addItem(_("No linked project"), _UNLINKED_PROJECT)
        inventory = view_model.project_inventory()
        if inventory.ok:
            projects, self._items = inventory.value
            self._projects = projects
            for project in projects:
                self.project_combo.addItem(project.name + (" (" + _("Archived") + ")" if project.archived else ""), project.id)
        self.item_combo.addItem(_("All work items"), None)
        self.item_combo.setEnabled(False)
        for field, caption in ((self.type_combo, _("Entry type")), (self.project_combo, _("Project")), (self.item_combo, _("Work item"))):
            field.setMinimumWidth(0)
            field.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            field.setMinimumContentsLength(8)
            field.setAccessibleName(caption)
            filters.addWidget(field, 1)
        root.addLayout(filters)
        self.results = QTreeWidget()
        self.results.setObjectName("record_search_tree_view")
        self.results.setHeaderLabels([_("Date"), _("Time"), _("Classification"), _("Project"), _("Work item"), _("Content")])
        self.results.setRootIsDecorated(False)
        self.results.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        configure_data_tree(self.results, (100, 160, 150, 100, 110, 180), stretch_column=5)
        root.addWidget(self.results, 1)
        self.status_label = QLabel()
        self.status_label.setObjectName("record_search_status_label")
        self.status_label.setWordWrap(True)
        self.status_label.setProperty("role", "secondary")
        footer = QHBoxLayout()
        self.more_button = QPushButton(_("More records"))
        set_button_icon(self.more_button, "chevron-down")
        self.open_button = QPushButton(_("Edit record"))
        self.open_button.setProperty("variant", "primary")
        set_button_icon(self.open_button, "pencil")
        self.close_button = QPushButton(_("Close"))
        self.associate_button = QPushButton(_("Assign context"))
        set_button_icon(self.associate_button, "pencil")
        self.associate_button.setAutoDefault(False)
        for button in (self.more_button, self.open_button, self.close_button):
            button.setAutoDefault(False)
        results_status = QHBoxLayout()
        results_status.addWidget(self.status_label, 1)
        results_status.addWidget(self.more_button)
        root.addLayout(results_status)
        footer.addWidget(self.associate_button)
        footer.addStretch()
        footer.addWidget(self.close_button)
        footer.addWidget(self.open_button)
        root.addLayout(footer)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(350)
        self._debounce.timeout.connect(self._reload)
        self.date_range.range_changed.connect(self._schedule)
        self.type_combo.currentIndexChanged.connect(self._schedule)
        self.project_combo.currentIndexChanged.connect(self._project_changed)
        self.item_combo.currentIndexChanged.connect(self._schedule)
        self.search_input.textChanged.connect(self._schedule)
        self.search_input.returnPressed.connect(self._reload)
        self.more_button.clicked.connect(lambda: self._reload(append=True))
        self.open_button.clicked.connect(self._open)
        self.associate_button.clicked.connect(self._associate)
        self.close_button.clicked.connect(self.reject)
        self.results.itemSelectionChanged.connect(self._actions)
        self.results.itemActivated.connect(lambda *_args: self._open())
        if criteria is not None:
            self.date_range.set_custom_range(criteria.start, criteria.end)
            self.date_range.setEnabled(False)
            with QSignalBlocker(self.project_combo), QSignalBlocker(self.item_combo):
                project_index = self.project_combo.findData(criteria.project_id) if criteria.project_id is not None else (
                    self.project_combo.findData(_UNLINKED_PROJECT) if criteria.unclassified and not criteria.project_label else -1)
                if project_index >= 0:
                    self.project_combo.setCurrentIndex(project_index)
                elif criteria.project_label or criteria.unclassified:
                    self.project_combo.addItem(criteria.project_label or _("No linked project"),
                                               _UNLINKED_PROJECT if criteria.unclassified else criteria.project_id)
                    self.project_combo.setCurrentIndex(self.project_combo.count() - 1)
                self.item_combo.clear()
                self.item_combo.addItem(_("All work items"), None)
                for item in self._items.get(criteria.project_id, ()):
                    self.item_combo.addItem(item.title, item.id)
                item_index = self.item_combo.findData(criteria.work_item_id) if criteria.work_item_id is not None else -1
                if item_index >= 0:
                    self.item_combo.setCurrentIndex(item_index)
                elif criteria.work_item_label is not None:
                    self.item_combo.addItem(criteria.work_item_label or _("No work item"), criteria.work_item_id)
                    self.item_combo.setCurrentIndex(self.item_combo.count() - 1)
            for field in (self.start_input, self.end_input, self.project_combo, self.item_combo):
                field.setEnabled(False)
            self.setWindowTitle(_("Project records"))
        shortcut = QShortcut(QKeySequence.StandardKey.Find, self)
        shortcut.activated.connect(self.search_input.setFocus)
        self._reload()
        self.search_input.setFocus()

    def _project_changed(self):
        with QSignalBlocker(self.item_combo):
            self.item_combo.clear()
            self.item_combo.addItem(_("All work items"), None)
            for item in self._items.get(self.project_combo.currentData(), ()):
                self.item_combo.addItem(item.title + (" (" + _("Archived") + ")" if item.archived else ""), item.id)
        self.item_combo.setEnabled(self.item_combo.count() > 1)
        self._schedule()

    def _schedule(self, *_args):
        self._version += 1
        self._loading = True
        self._actions()
        self._debounce.start()

    def _criteria(self):
        if self._fixed_criteria is not None:
            from dataclasses import replace
            return replace(self._fixed_criteria, text=self.search_input.text(), entry_type=self.type_combo.currentData())
        project_id = self.project_combo.currentData()
        unlinked = project_id == _UNLINKED_PROJECT
        return EntryFilter(*self.date_range.bounds(), text=self.search_input.text(),
                           entry_type=self.type_combo.currentData(), project_id=None if unlinked else project_id,
                           work_item_id=None if unlinked else self.item_combo.currentData(), unclassified=unlinked)

    def _reload(self, *, append=False):
        self._debounce.stop()
        self._version += 1
        version = self._version
        if self._job is not None:
            self._job.cancel()
        try:
            criteria = self._criteria()
        except ValueError:
            self.status_label.setText(display_error_code("record_search_invalid"))
            self._loading = True
            self._actions()
            return
        cursor = self._cursor if append else None
        self._loading = True
        self.status_label.setText(_("Searching..."))
        self._actions()
        def completed(result):
            if not isValid(self) or version != self._version:
                return
            self._job = None
            self._loading = not result.ok
            if not result.ok:
                self.status_label.setText(display_error_message(result.error))
                self._actions()
                return
            if not append:
                self.results.clear()
            for entry in result.value.entries:
                span = f"{entry.start_time} - {entry.end_time}" if entry.has_times else _("All day")
                project_label = entry.context.project_label or _("No linked project")
                if entry.context.project_label and entry.context.project_id is None:
                    project_label += " (" + _("Unlinked") + ")"
                preview = entry.note.replace("\n", " ")
                if len(preview) > 120:
                    preview = preview[:120] + "..."
                row = QTreeWidgetItem([entry.day.isoformat(), span + "  " + duration_label(entry.raw_hours()),
                    classification_label(entry.entry_type, entry.work_mode), project_label,
                    entry.context.work_item_label or _("No work item"), preview])
                row.setData(0, Qt.ItemDataRole.UserRole, entry)
                set_data_tooltips(row, {5: entry.note})
                self.results.addTopLevelItem(row)
            self._cursor = result.value.next_cursor
            count = self.results.topLevelItemCount()
            self.status_label.setText(_("Showing {count} records").format(count=count) if count else _("No matching records."))
            self._actions()
        operation = lambda: self._model.search(criteria, cursor=cursor)
        if self._runner is None:
            completed(operation())
        else:
            try:
                job = self._runner.submit("record_search", lambda _token: operation(), on_complete=completed)
                if self._loading:
                    self._job = job
            except Exception:
                completed(Result.failure(InfrastructureError("record_search_failed", "record_search_failed")))

    def _actions(self):
        selected = self.results.selectedItems()
        count = len(selected)
        entries = (row.data(0, Qt.ItemDataRole.UserRole) for row in selected)
        work_only = all(entry.entry_type.category == EntryCategory.WORK for entry in entries)
        self.open_button.setEnabled(not self._loading and count == 1)
        self.associate_button.setEnabled(not self._loading and 1 <= count <= 250 and work_only
            and bool(getattr(self._model, "projects_available", False)) and bool(getattr(self._model, "changes_available", False)))
        self.associate_button.setToolTip(_("Project assignment is available for work records only.") if not work_only else "")
        self.more_button.setEnabled(not self._loading and self._cursor is not None)

    def _associate(self):
        if not self.associate_button.isEnabled():
            return
        from worklogger.presentation.widgets.batch_context import BatchContextDialog
        entries = tuple(row.data(0, Qt.ItemDataRole.UserRole) for row in self.results.selectedItems())
        dialog = BatchContextDialog(self._model, entries, self._projects, self._items, self, job_runner=self._runner)
        def applied(_entries):
            self.records_changed.emit()
            self._reload()
        dialog.applied.connect(applied)
        dialog.finished.connect(dialog.deleteLater)
        dialog.open()

    def _open(self):
        row = self.results.currentItem()
        if not self._loading and row is not None and len(self.results.selectedItems()) == 1:
            record = row.data(0, Qt.ItemDataRole.UserRole)
            if self._selection_handler is None or self._selection_handler(record):
                self.entry_selected.emit(record)
                self.accept()

    def done(self, result):
        self._version += 1
        self._debounce.stop()
        if self._job is not None:
            self._job.cancel()
        super().done(result)
