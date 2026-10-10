"""Compact project and work-item selection for record drafts."""

from PySide6.QtCore import Signal, QSignalBlocker
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from worklogger.domain.projects.models import WorkContext
from worklogger.infrastructure.i18n import _


class WorkContextPicker(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("work_context_picker_widget")
        self._projects, self._items = (), {}
        self._snapshot = WorkContext()
        self.project_combo = QComboBox()
        self.work_item_combo = QComboBox()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        for field, label, name in ((self.project_combo, _("Project"), "project_combo"),
                                   (self.work_item_combo, _("Work item"), "work_item_combo")):
            field.setObjectName(name)
            field.setAccessibleName(label)
            field.setMinimumWidth(0)
            field.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            field.setMinimumContentsLength(1)
            caption = QLabel(label)
            caption.setBuddy(field)
            column = QVBoxLayout()
            column.setSpacing(3)
            column.addWidget(caption)
            column.addWidget(field)
            row.addLayout(column, 1)
        self.project_combo.currentIndexChanged.connect(self._project_changed)
        self.work_item_combo.currentIndexChanged.connect(self._item_changed)
        self.set_context(WorkContext())

    def set_inventory(self, projects, items):
        context = self.context()
        self._projects, self._items = projects, items
        self.set_context(context)

    def set_context(self, context):
        self._snapshot = context
        with QSignalBlocker(self.project_combo), QSignalBlocker(self.work_item_combo):
            self.project_combo.clear()
            self.project_combo.addItem(_("Unclassified"), None)
            for project in self._projects:
                if not project.archived:
                    self.project_combo.addItem(project.name, project.id)
            if context.project_id and self.project_combo.findData(context.project_id) < 0:
                self.project_combo.addItem(context.project_label, context.project_id)
            if context.project_id is None and context.project_label:
                self.project_combo.addItem(context.project_label + " (" + _("Unlinked") + ")", "unlinked")
            selected = "unlinked" if context.project_id is None and context.project_label else context.project_id
            self.project_combo.setCurrentIndex(max(0, self.project_combo.findData(selected)))
            self._populate_items(context.work_item_id)
            self.project_combo.setToolTip(self.project_combo.currentText())

    def _populate_items(self, selected=None):
        project_id = self.project_combo.currentData()
        self.work_item_combo.clear()
        self.work_item_combo.addItem(_("No work item"), None)
        if project_id == "unlinked" and self._snapshot.work_item_label:
            self.work_item_combo.setItemText(0, self._snapshot.work_item_label)
        for item in self._items.get(project_id, ()):
            if not item.archived:
                self.work_item_combo.addItem(item.title, item.id)
        if selected and self.work_item_combo.findData(selected) < 0 and project_id == self._snapshot.project_id:
            self.work_item_combo.addItem(self._snapshot.work_item_label, selected)
        self.work_item_combo.setCurrentIndex(max(0, self.work_item_combo.findData(selected)))
        self.work_item_combo.setEnabled(project_id is not None and project_id != "unlinked")
        self.work_item_combo.setToolTip(self.work_item_combo.currentText())

    def _project_changed(self):
        with QSignalBlocker(self.work_item_combo):
            self._populate_items()
        self.project_combo.setToolTip(self.project_combo.currentText())
        self.changed.emit()

    def _item_changed(self):
        self.work_item_combo.setToolTip(self.work_item_combo.currentText())
        self.changed.emit()

    def context(self):
        project_id, item_id = self.project_combo.currentData(), self.work_item_combo.currentData()
        if project_id == "unlinked":
            return self._snapshot
        if project_id is None:
            return WorkContext()
        return WorkContext(project_id, item_id, self.project_combo.currentText(), self.work_item_combo.currentText() if item_id else "")
