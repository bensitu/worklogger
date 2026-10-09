"""Account-specific classification editor."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QVBoxLayout)

from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.widgets.assets import apply_window_icon
from worklogger.presentation.widgets.icons import set_button_icon
from worklogger.presentation.widgets.two_line_delegate import TwoLineItemDelegate


class WorkTypeManagerDialog(QDialog):
    def __init__(self, view_model, parent=None):
        super().__init__(parent)
        self._view_model = view_model
        self._selected = None
        self.setObjectName("work_type_manager_dialog")
        self.setWindowTitle(_("Work types"))
        apply_window_icon(self)
        self.resize(700, 420)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        body = QHBoxLayout()
        self.type_list = QListWidget()
        self.type_list.setObjectName("custom_work_type_list_widget")
        self.type_list.setMinimumWidth(240)
        self.type_list.setItemDelegate(TwoLineItemDelegate(self.type_list))
        self.type_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.type_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        body.addWidget(self.type_list, 1)
        editor = QVBoxLayout()
        self.name_input = QLineEdit()
        self.name_input.setMaxLength(80)
        self.name_input.setAccessibleName(_("Name"))
        self.category_combo = QComboBox()
        for caption, category in ((_("Work"), "work"), (_("Break"), "break"), (_("Leave"), "leave")):
            self.category_combo.addItem(caption, category)
        self.category_combo.setAccessibleName(_("Accounting category"))
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.addRow(_("Name"), self.name_input)
        form.addRow(_("Accounting category"), self.category_combo)
        editor.addLayout(form)
        description = QLabel(_("Changes apply to new records. Existing records keep their saved name and accounting category."))
        description.setWordWrap(True)
        description.setProperty("role", "secondary")
        editor.addWidget(description)
        editor.addStretch()
        self.save_button = QPushButton(_("Save"))
        self.save_button.setProperty("variant", "primary")
        set_button_icon(self.save_button, "save")
        editor.addWidget(self.save_button)
        body.addLayout(editor, 1)
        root.addLayout(body, 1)
        footer = QHBoxLayout()
        self.new_button = QPushButton(_("New type"))
        self.archive_button = QPushButton(_("Archive type"))
        self.close_button = QPushButton(_("Close"))
        for button, icon in ((self.new_button, "plus"), (self.archive_button, "eye-off")):
            set_button_icon(button, icon)
            footer.addWidget(button)
        footer.addStretch()
        footer.addWidget(self.close_button)
        root.addLayout(footer)
        for button in (self.new_button, self.archive_button, self.save_button, self.close_button):
            button.setAutoDefault(False)
            button.setMinimumHeight(36)
        self.new_button.clicked.connect(self._new)
        self.archive_button.clicked.connect(self._archive)
        self.save_button.clicked.connect(self._save)
        self.close_button.clicked.connect(self.accept)
        self.type_list.currentItemChanged.connect(self._select)
        self.name_input.textChanged.connect(lambda text: self.save_button.setEnabled(bool(text.strip())))
        self._reload()
        self._new()

    def _reload(self):
        result = self._view_model.list_work_types()
        if not self._check(result):
            return
        self.type_list.clear()
        for definition in result.value:
            if definition.archived:
                continue
            caption = self.category_combo.itemText(self.category_combo.findData(definition.category))
            item = QListWidgetItem(definition.label + "\n" + caption)
            item.setData(Qt.ItemDataRole.UserRole, definition)
            self.type_list.addItem(item)

    def _new(self):
        self.type_list.clearSelection()
        self._selected = None
        self.name_input.clear()
        self.category_combo.setCurrentIndex(0)
        self.archive_button.setEnabled(False)
        self.name_input.setFocus()

    def _select(self, item, _previous):
        self._selected = item.data(Qt.ItemDataRole.UserRole) if item else None
        if self._selected:
            self.name_input.setText(self._selected.label)
            self.category_combo.setCurrentIndex(self.category_combo.findData(self._selected.category))
        self.archive_button.setEnabled(self._selected is not None)

    def _save(self):
        result = self._view_model.save_work_type(self.name_input.text(), self.category_combo.currentData(), self._selected)
        if self._check(result):
            self._reload()
            for row in range(self.type_list.count()):
                if self.type_list.item(row).data(Qt.ItemDataRole.UserRole).value == result.value.value:
                    self.type_list.setCurrentRow(row)
                    break

    def _archive(self):
        if self._selected is None:
            return
        if QMessageBox.question(self, _("Archive type"),
            _("Hide this type from new records? Existing records will not change."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        if self._check(self._view_model.archive_work_type(self._selected)):
            self._reload()
            self._new()

    def _check(self, result):
        if not result.ok:
            QMessageBox.warning(self, _("Work types"), display_error_message(result.error))
        return result.ok
