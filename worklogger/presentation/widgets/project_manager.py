"""Project and work-item management with recoverable edits and background storage."""

from PySide6.QtCore import Qt, Signal, QSignalBlocker
from PySide6.QtWidgets import (QCheckBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QTabWidget, QVBoxLayout, QWidget)
from shiboken6 import isValid

from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.widgets.assets import apply_window_icon
from worklogger.presentation.widgets.icons import set_button_icon
from worklogger.presentation.widgets.two_line_delegate import TwoLineItemDelegate


class ProjectManagerDialog(QDialog):
    changed = Signal()

    def __init__(self, view_model, parent=None, *, job_runner=None):
        super().__init__(parent)
        self._model, self._runner = view_model, job_runner
        self._projects, self._items = (), {}
        self._project = self._item = None
        self._busy = False
        self.setObjectName("project_manager_dialog")
        self.setWindowTitle(_("Projects"))
        apply_window_icon(self)
        self.resize(840, 600)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        self.body_widget = QWidget()
        body = QHBoxLayout(self.body_widget)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(20)
        self.project_list = self._list("project_list_widget")
        self.project_list.setMinimumWidth(220)
        body.addWidget(self.project_list, 1)
        self.editor_tabs = QTabWidget()
        self.editor_tabs.setObjectName("project_editor_tab_widget")
        body.addWidget(self.editor_tabs, 2)
        project_page = QWidget()
        project_layout = QVBoxLayout(project_page)
        self.project_name_input = self._input(_("Name"), 120)
        self.project_code_input = self._input(_("Code"), 40)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.addRow(_("Name"), self.project_name_input)
        form.addRow(_("Code"), self.project_code_input)
        project_layout.addLayout(form)
        project_layout.addStretch()
        row = QHBoxLayout()
        self.project_new_button = self._button(_("New project"), "plus", self._new_project)
        self.project_archive_button = self._button(_("Archive project"), "eye-off", self._archive_project)
        self.project_save_button = self._button(_("Save"), "save", self._save_project, primary=True)
        for button in (self.project_new_button, self.project_archive_button, self.project_save_button):
            row.addWidget(button)
        project_layout.addLayout(row)
        self.editor_tabs.addTab(project_page, _("Project"))
        item_page = QWidget()
        item_layout = QVBoxLayout(item_page)
        self.work_item_list = self._list("work_item_list_widget")
        self.work_item_list.setMinimumHeight(130)
        item_layout.addWidget(self.work_item_list, 1)
        self.work_item_title_input = self._input(_("Title"), 240)
        self.work_item_url_input = self._input(_("Source URL"), 2048)
        self.completed_checkbox = QCheckBox(_("Completed"))
        self.completed_checkbox.setObjectName("work_item_completed_check")
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.addRow(_("Title"), self.work_item_title_input)
        form.addRow(_("Source URL"), self.work_item_url_input)
        form.addRow(self.completed_checkbox)
        item_layout.addLayout(form)
        row = QHBoxLayout()
        self.work_item_new_button = self._button(_("New work item"), "plus", self._new_item)
        self.work_item_archive_button = self._button(_("Archive work item"), "eye-off", self._archive_item)
        self.work_item_save_button = self._button(_("Save"), "save", self._save_item, primary=True)
        for button in (self.work_item_new_button, self.work_item_archive_button, self.work_item_save_button):
            row.addWidget(button)
        item_layout.addLayout(row)
        self.editor_tabs.addTab(item_page, _("Work items"))
        root.addWidget(self.body_widget, 1)
        self.status_label = QLabel()
        self.status_label.setObjectName("project_status_label")
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self.status_label)
        self.close_button = self._button(_("Close"), None, self.reject)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(self.close_button)
        root.addLayout(footer)
        self._baseline = self._values()
        self._active_tab = 0
        self.editor_tabs.currentChanged.connect(self._tab_changed)
        self.project_list.currentItemChanged.connect(self._select_project)
        self.work_item_list.currentItemChanged.connect(self._select_item)
        self._reload()

    @staticmethod
    def _list(name):
        widget = QListWidget()
        widget.setObjectName(name)
        widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        widget.setItemDelegate(TwoLineItemDelegate(widget))
        return widget

    @staticmethod
    def _input(caption, maximum):
        widget = QLineEdit()
        widget.setAccessibleName(caption)
        widget.setMaxLength(maximum)
        return widget

    @staticmethod
    def _button(caption, icon, callback, *, primary=False):
        button = QPushButton(caption)
        button.setAutoDefault(False)
        button.setProperty("variant", "primary" if primary else "outline")
        if icon:
            set_button_icon(button, icon)
        button.clicked.connect(callback)
        return button

    def _values(self):
        return (self.project_name_input.text(), self.project_code_input.text(),
                self.work_item_title_input.text(), self.work_item_url_input.text(), self.completed_checkbox.isChecked())

    def _guard(self):
        if self._values() == self._baseline:
            return True
        return QMessageBox.question(self, _("Unsaved changes"), _("Discard unsaved changes?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def _run(self, operation, completed):
        if self._busy:
            return
        self._busy = True
        self.body_widget.setEnabled(False)
        self.close_button.setEnabled(False)
        self.status_label.clear()
        def done(result):
            if not isValid(self):
                return
            self._busy = False
            self.body_widget.setEnabled(True)
            self.close_button.setEnabled(True)
            if not result.ok:
                self.status_label.setText(display_error_message(result.error))
                return
            completed(result.value)
        if self._runner is None:
            done(operation())
        else:
            try:
                self._runner.submit("project_update", lambda _token: operation(), on_complete=done)
            except Exception:
                done(Result.failure(InfrastructureError("work_context_operation_failed", "work_context_operation_failed")))

    def _reload(self, project_id=None, item_id=None):
        def show(catalog):
            self._projects, self._items = catalog
            with QSignalBlocker(self.project_list):
                self.project_list.clear()
                for project in self._projects:
                    if not project.archived:
                        row = QListWidgetItem(project.name + ("\n" + project.code if project.code else ""))
                        row.setData(Qt.ItemDataRole.UserRole, project)
                        self.project_list.addItem(row)
                chosen = next((self.project_list.item(index) for index in range(self.project_list.count())
                               if self.project_list.item(index).data(Qt.ItemDataRole.UserRole).id == project_id), None)
                if chosen is None and self.project_list.count():
                    chosen = self.project_list.item(0)
                self.project_list.setCurrentItem(chosen)
            self._render_project(chosen.data(Qt.ItemDataRole.UserRole) if chosen else None, item_id)
        self._run(self._model.inventory, show)

    def _render_project(self, project, item_id=None):
        self._project = project
        self.project_name_input.setText(project.name if project else "")
        self.project_code_input.setText(project.code if project else "")
        self.project_archive_button.setEnabled(project is not None)
        with QSignalBlocker(self.editor_tabs):
            self.editor_tabs.setTabEnabled(1, project is not None)
        self._active_tab = self.editor_tabs.currentIndex()
        with QSignalBlocker(self.work_item_list):
            self.work_item_list.clear()
            chosen = None
            for item in self._items.get(project.id if project else None, ()):
                if not item.archived:
                    row = QListWidgetItem(item.title + ("\n" + _("Completed") if item.completed else ""))
                    row.setData(Qt.ItemDataRole.UserRole, item)
                    self.work_item_list.addItem(row)
                    if item.id == item_id:
                        chosen = row
            self.work_item_list.setCurrentItem(chosen)
        self._render_item(chosen.data(Qt.ItemDataRole.UserRole) if chosen else None)

    def _render_item(self, item):
        self._item = item
        self.work_item_title_input.setText(item.title if item else "")
        self.work_item_url_input.setText(item.source_url if item else "")
        self.completed_checkbox.setChecked(item.completed if item else False)
        self.work_item_archive_button.setEnabled(item is not None)
        self._baseline = self._values()

    def _select_project(self, row, previous):
        if self._guard():
            self._render_project(row.data(Qt.ItemDataRole.UserRole) if row else None)
        else:
            with QSignalBlocker(self.project_list):
                self.project_list.setCurrentItem(previous)

    def _select_item(self, row, previous):
        if self._guard():
            self._render_item(row.data(Qt.ItemDataRole.UserRole) if row else None)
        else:
            with QSignalBlocker(self.work_item_list):
                self.work_item_list.setCurrentItem(previous)

    def _new_project(self):
        if self._guard():
            with QSignalBlocker(self.project_list):
                self.project_list.setCurrentItem(None)
            self._render_project(None)
            self.editor_tabs.setCurrentIndex(0)
            self.project_name_input.setFocus()

    def _tab_changed(self, index):
        if not self._guard():
            with QSignalBlocker(self.editor_tabs):
                self.editor_tabs.setCurrentIndex(self._active_tab)
            return
        self._active_tab = index
        self._render_project(self._project, self._item.id if self._item else None)

    def _new_item(self):
        if self._guard():
            with QSignalBlocker(self.work_item_list):
                self.work_item_list.setCurrentItem(None)
            self._render_item(None)
            self.work_item_title_input.setFocus()

    def _save_project(self):
        name, code, previous = self.project_name_input.text(), self.project_code_input.text(), self._project
        def completed(project):
            self._reload(project.id)
            self.changed.emit()
        self._run(lambda: self._model.save_project(name, code, previous), completed)

    def _save_item(self):
        if self._project is None:
            return
        project_id, previous = self._project.id, self._item
        title, url, finished = self.work_item_title_input.text(), self.work_item_url_input.text(), self.completed_checkbox.isChecked()
        def completed(item):
            self._reload(project_id, item.id)
            self.changed.emit()
        self._run(lambda: self._model.save_work_item(project_id, title, url, finished, previous), completed)

    def _confirm_archive(self):
        return self._guard() and QMessageBox.question(self, _("Archive"),
            _("Hide this item from new records? Existing records will not change."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def _archive_project(self):
        project = self._project
        if project and self._confirm_archive():
            self._run(lambda: self._model.archive_project(project), self._archived)

    def _archive_item(self):
        item = self._item
        if item and self._confirm_archive():
            self._run(lambda: self._model.archive_work_item(item), lambda _value: self._archived(None, item.project_id))

    def _archived(self, _value, project_id=None):
        self._reload(project_id)
        self.changed.emit()

    def reject(self):
        if not self._busy and self._guard():
            super().reject()

    def closeEvent(self, event):
        if self._busy:
            event.ignore()
        else:
            super().closeEvent(event)
