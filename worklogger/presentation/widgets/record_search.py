"""Debounced, paged record search that preserves keyboard focus and draft editing."""

from datetime import date
from PySide6.QtCore import Qt, QTimer, Signal, QSignalBlocker
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDialog, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout)
from shiboken6 import isValid

from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkType
from worklogger.domain.worklog.search import EntryFilter
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_code, display_error_message
from worklogger.presentation.widgets.assets import apply_window_icon
from worklogger.presentation.widgets.icons import set_button_icon
from worklogger.presentation.work_type_labels import work_type_label
from worklogger.presentation.date_labels import duration_label


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
        self.search_input = QLineEdit()
        self.search_input.setObjectName("record_search_line_edit")
        self.search_input.setPlaceholderText(_("Search records"))
        self.search_input.setAccessibleName(_("Search records"))
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMaxLength(512)
        root.addWidget(self.search_input)
        dates = QHBoxLayout()
        self.start_input, self.end_input = QDateEdit(), QDateEdit()
        for field, caption, value in ((self.start_input, _("From"), selected_day.replace(day=1)),
                                     (self.end_input, _("To"), selected_day)):
            field.setDisplayFormat("yyyy-MM-dd")
            field.setCalendarPopup(True)
            field.setDateRange(date.min, date.max)
            field.setDate(value)
            field.setAccessibleName(caption)
            label = QLabel(caption)
            label.setBuddy(field)
            dates.addWidget(label)
            dates.addWidget(field, 1)
        root.addLayout(dates)
        filters = QHBoxLayout()
        self.type_combo = QComboBox()
        self.project_combo = QComboBox()
        self.item_combo = QComboBox()
        self.type_combo.addItem(_("All work types"), None)
        for value in WorkType:
            self.type_combo.addItem(work_type_label(value), value.value)
        types = view_model.list_work_types()
        if types.ok:
            for value in types.value:
                self.type_combo.addItem(value.label, value.value)
        self.project_combo.addItem(_("All projects"), None)
        inventory = view_model.project_inventory()
        if inventory.ok:
            projects, self._items = inventory.value
            self._projects = projects
            for project in projects:
                self.project_combo.addItem(project.name + (" (" + _("Archived") + ")" if project.archived else ""), project.id)
        self.item_combo.addItem(_("All work items"), None)
        for field, caption in ((self.type_combo, _("Work type")), (self.project_combo, _("Project")), (self.item_combo, _("Work item"))):
            field.setMinimumWidth(0)
            field.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            field.setMinimumContentsLength(8)
            field.setAccessibleName(caption)
            filters.addWidget(field, 1)
        root.addLayout(filters)
        self.unclassified_check = QCheckBox(_("Unclassified"))
        self.unclassified_check.setObjectName("unclassified_records_check")
        root.addWidget(self.unclassified_check)
        self.results = QTreeWidget()
        self.results.setObjectName("record_search_tree_view")
        self.results.setHeaderLabels([_("Date"), _("Time"), _("Work type"), _("Project"), _("Work item"), _("Content")])
        self.results.setRootIsDecorated(False)
        self.results.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.results.setUniformRowHeights(True)
        self.results.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.results.header().setStretchLastSection(True)
        self.results.setColumnWidth(0, 100)
        self.results.setColumnWidth(1, 160)
        root.addWidget(self.results, 1)
        self.status_label = QLabel()
        self.status_label.setObjectName("record_search_status_label")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
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
        footer.addWidget(self.more_button)
        footer.addWidget(self.associate_button)
        footer.addStretch()
        footer.addWidget(self.close_button)
        footer.addWidget(self.open_button)
        root.addLayout(footer)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(350)
        self._debounce.timeout.connect(self._reload)
        for field in (self.start_input, self.end_input):
            field.dateChanged.connect(self._schedule)
        self.type_combo.currentIndexChanged.connect(self._schedule)
        self.project_combo.currentIndexChanged.connect(self._project_changed)
        self.item_combo.currentIndexChanged.connect(self._schedule)
        self.unclassified_check.toggled.connect(self._unclassified_changed)
        self.search_input.textChanged.connect(self._schedule)
        self.search_input.returnPressed.connect(self._reload)
        self.more_button.clicked.connect(lambda: self._reload(append=True))
        self.open_button.clicked.connect(self._open)
        self.associate_button.clicked.connect(self._associate)
        self.close_button.clicked.connect(self.reject)
        self.results.itemSelectionChanged.connect(self._actions)
        self.results.itemActivated.connect(lambda *_args: self._open())
        if criteria is not None:
            self.start_input.setDate(criteria.start)
            self.end_input.setDate(criteria.end)
            for field in (self.start_input, self.end_input, self.project_combo, self.item_combo, self.unclassified_check):
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
        self._schedule()

    def _unclassified_changed(self, checked):
        self.project_combo.setEnabled(not checked)
        self.item_combo.setEnabled(not checked)
        self._schedule()

    def _schedule(self, *_args):
        self._version += 1
        self._loading = True
        self._actions()
        self._debounce.start()

    def _criteria(self):
        if self._fixed_criteria is not None:
            from dataclasses import replace
            return replace(self._fixed_criteria, text=self.search_input.text(), work_type=self.type_combo.currentData())
        return EntryFilter(self.start_input.date().toPython(), self.end_input.date().toPython(), self.search_input.text(),
                           self.type_combo.currentData(), self.project_combo.currentData() if not self.unclassified_check.isChecked() else None,
                           self.item_combo.currentData() if not self.unclassified_check.isChecked() else None, self.unclassified_check.isChecked())

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
                project_label = entry.context.project_label
                if project_label and entry.context.project_id is None:
                    project_label += " (" + _("Unlinked") + ")"
                row = QTreeWidgetItem([entry.day.isoformat(), span + "  " + duration_label(entry.raw_hours()),
                    work_type_label(entry.work_type), project_label, entry.context.work_item_label,
                    entry.note.replace("\n", " ")[:120]])
                row.setData(0, Qt.ItemDataRole.UserRole, entry)
                row.setToolTip(5, entry.note)
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
        count = len(self.results.selectedItems())
        self.open_button.setEnabled(not self._loading and count == 1)
        self.associate_button.setEnabled(not self._loading and 1 <= count <= 250
            and bool(getattr(self._model, "projects_available", False)) and bool(getattr(self._model, "changes_available", False)))
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
