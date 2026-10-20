"""Account-specific classification editor."""

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidgetItem, QMessageBox,
    QPushButton, QVBoxLayout)

from worklogger.infrastructure.i18n import _
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.job_runner import owned_callback
from worklogger.presentation.widgets.assets import apply_window_icon
from worklogger.presentation.widgets.icons import set_button_icon
from worklogger.presentation.widgets.preview_list import PreviewListWidget
from worklogger.presentation.widgets.entry_type_options import entry_type_icon


class ClassificationManagerDialog(QDialog):
    def __init__(self, view_model, parent=None, *, work_modes=False, job_runner=None):
        super().__init__(parent)
        self._view_model = view_model
        self._selected = None
        self._work_modes = work_modes
        self._runner = job_runner
        self._busy = False
        self.setObjectName("entry_type_manager_dialog")
        self.setWindowTitle(_("Work arrangements") if work_modes else _("Entry types"))
        apply_window_icon(self)
        self.resize(700, 420)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        body = QHBoxLayout()
        self.type_list = PreviewListWidget(framed=True, spacing=0)
        self.type_list.setObjectName("entry_type_list_widget")
        self.type_list.setMinimumWidth(240)
        self.type_list.setIconSize(QSize(4, 20))
        self.type_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        body.addWidget(self.type_list, 1)
        editor = QVBoxLayout()
        self.name_input = QLineEdit()
        self.name_input.setMaxLength(80)
        self.name_input.setAccessibleName(_("Name"))
        self.category_combo = QComboBox(self)
        for caption, category in ((_("Work"), "work"), (_("Break"), "break"), (_("Leave"), "leave")):
            self.category_combo.addItem(caption, category)
        self.category_combo.setAccessibleName(_("Accounting category"))
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.addRow(_("Name"), self.name_input)
        if not work_modes:
            form.addRow(_("Accounting category"), self.category_combo)
        self.category_combo.setVisible(not work_modes)
        editor.addLayout(form)
        description = QLabel(_("Changes apply to new records. Existing records keep their saved work arrangement name.") if work_modes
            else _("Changes apply to new records. Existing records keep their saved name and accounting category."))
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
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        footer = QHBoxLayout()
        self.new_button = QPushButton(_("New arrangement") if work_modes else _("New type"))
        self.archive_button = QPushButton(_("Archive arrangement") if work_modes else _("Archive type"))
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
        self._run(self._view_model.list_types, lambda result: self._show_types(result.value))

    def _show_types(self, definitions, selected_id=None):
        self.type_list.clear()
        for definition in definitions:
            if definition.archived:
                continue
            caption = self.category_combo.itemText(self.category_combo.findData(definition.category))
            item = QListWidgetItem(entry_type_icon(definition), definition.label if self._work_modes else definition.label + "\n" + caption)
            item.setData(Qt.ItemDataRole.UserRole, definition)
            self.type_list.addItem(item)
            if definition.value == selected_id:
                self.type_list.setCurrentItem(item)

    def _new(self):
        self.type_list.setCurrentRow(-1)
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
        name, category, selected = self.name_input.text(), self.category_combo.currentData(), self._selected
        def save():
            saved = self._view_model.save_type(name, category, selected)
            if not saved.ok:
                return saved
            loaded = self._view_model.list_types()
            return Result.success((loaded.value, saved.value.value)) if loaded.ok else loaded
        self._run(save, lambda result: self._show_types(*result.value))

    def _archive(self):
        if self._selected is None:
            return
        if QMessageBox.question(self, _("Archive arrangement") if self._work_modes else _("Archive type"),
            _("Hide this type from new records? Existing records will not change."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        selected = self._selected
        def archive():
            result = self._view_model.archive_type(selected)
            return self._view_model.list_types() if result.ok else result
        def complete(result):
            self._show_types(result.value)
            self._new()
        self._run(archive, complete)

    def _run(self, operation, completed):
        if self._busy:
            return
        if self._runner is None:
            result = operation()
            if self._check(result):
                completed(result)
            return
        self._busy = True
        self.setEnabled(False)
        def complete(result):
            self._busy = False
            self.setEnabled(True)
            if self._check(result):
                completed(result)
        try:
            self._runner.submit("classification_update", lambda _token: operation(), on_complete=owned_callback(self, complete))
        except Exception:
            complete(Result.failure(InfrastructureError("entry_types_save_failed", "entry_types_save_failed")))

    def reject(self):
        if not self._busy:
            super().reject()

    def _check(self, result):
        if not result.ok:
            self.status_label.setText(display_error_message(result.error))
        else:
            self.status_label.clear()
        return result.ok
