from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget, QListWidgetItem,
    QTextEdit, QMessageBox, QDialogButtonBox, QFormLayout, QLineEdit, QComboBox, QSplitter,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from utils.i18n import _, msg
from templates import (
    get_template, list_builtin_template_types, list_custom_templates,
    save_custom_template, delete_custom_template,
    TEMPLATE_DISPLAY_NAME,
)
from .common import _localize_msgbox_buttons, _render_template_with_context


class TemplatePickerDialog(QDialog):
    def __init__(self, app_ref, type_key: str = "daily",
                 current_content: str = "", parent=None):
        super().__init__(parent)
        self._app = app_ref
        self._lang = app_ref.lang
        self._type = type_key
        self.setWindowTitle(_("Templates"))
        self.setMinimumSize(640, 480)
        self.resize(720, 540)

        self.chosen_content: str = ""
        self._editing_filename: str = ""

        lv = QVBoxLayout(self)
        lv.setSpacing(8)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setContentsMargins(5, 5, 5, 5)

        left_w = QWidget()
        lft = QVBoxLayout(left_w)
        lft.setContentsMargins(0, 0, 0, 0)
        lft.setSpacing(2)

        self._list = QListWidget()
        self._list.setMinimumWidth(200)
        self._list.currentItemChanged.connect(self._on_select)
        lft.addWidget(self._list)

        lft_btns = QHBoxLayout()
        self._del_btn = QPushButton(_("Delete"))
        self._del_btn.setEnabled(False)
        self._del_btn.clicked.connect(self._delete_selected)
        new_btn = QPushButton(f"+ {_("New Template")}")
        new_btn.clicked.connect(self._create_new)
        lft_btns.addWidget(new_btn)
        lft_btns.addWidget(self._del_btn)
        lft.addLayout(lft_btns)

        right_w = QWidget()
        rgt = QVBoxLayout(right_w)
        rgt.setContentsMargins(0, 0, 0, 0)
        rgt.setSpacing(2)

        self._loading = False

        self._preview = QTextEdit()
        self._preview.setFont(QFont("monospace", 10))
        self._preview.textChanged.connect(self._on_content_changed)
        rgt.addWidget(self._preview, 1)

        rgt_btns = QHBoxLayout()
        self._save_changes_btn = QPushButton(
            _("Save Changes"))
        self._save_changes_btn.setFixedWidth(150)
        self._save_changes_btn.setEnabled(False)
        self._save_changes_btn.clicked.connect(self._save_changes)
        rgt_btns.addStretch()
        rgt_btns.addWidget(self._save_changes_btn)
        rgt.addLayout(rgt_btns)

        splitter.addWidget(left_w)
        splitter.addWidget(right_w)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        lv.addWidget(splitter, 1)

        bot = QHBoxLayout()
        bot.setSpacing(6)
        insert_btn = QPushButton(_("Insert"))
        insert_btn.setObjectName("primary_btn")
        insert_btn.clicked.connect(self._insert)
        cancel_btn = QPushButton(_("Close"))
        cancel_btn.clicked.connect(self.reject)
        bot.addStretch()
        bot.addWidget(cancel_btn)
        bot.addWidget(insert_btn)
        lv.addLayout(bot)

        self._populate()

    def _populate(self):
        lang = self._lang
        self._list.clear()
        self._items: list[dict] = []

        discovered = list_builtin_template_types(lang)
        builtin_types = []
        if self._type in discovered:
            builtin_types.append(self._type)
        elif get_template(lang, self._type):
            builtin_types.append(self._type)
        for type_key in discovered:
            if type_key not in builtin_types:
                builtin_types.append(type_key)

        for builtin_type in builtin_types:
            content = get_template(lang, builtin_type)
            if not content:
                continue
            display_key = TEMPLATE_DISPLAY_NAME.get(builtin_type, builtin_type)
            item = QListWidgetItem(
                f"[{_("Built-in")}]  {msg(display_key)}")
            item.setData(Qt.UserRole, {
                "kind": "builtin",
                "content": content,
                "type_key": builtin_type,
            })
            self._list.addItem(item)
            self._items.append({
                "kind": "builtin",
                "content": content,
                "filename": "",
                "type_key": builtin_type,
            })

        for tpl in list_custom_templates(self._type):
            label = f"[{_("Custom")}]  {tpl['name']}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, {"kind": "custom",
                                       "content": tpl.get("content", ""),
                                       "filename": tpl["filename"]})
            self._list.addItem(item)
            self._items.append({"kind": "custom",
                                "content": tpl.get("content", ""),
                                "filename": tpl["filename"]})

        if self._list.count() == 0:
            placeholder = QListWidgetItem(_("No templates available for this type."))
            placeholder.setFlags(Qt.NoItemFlags)
            self._list.addItem(placeholder)
        else:
            self._list.setCurrentRow(0)

    def _on_select(self, current, _prev):
        if current is None:
            self._loading = True
            self._preview.setPlainText("")
            self._loading = False
            self._del_btn.setEnabled(False)
            self._save_changes_btn.setEnabled(False)
            self._editing_filename = ""
            return
        data = current.data(Qt.UserRole)
        if not data:
            self._del_btn.setEnabled(False)
            self._save_changes_btn.setEnabled(False)
            self._editing_filename = ""
            return
        is_custom = data["kind"] == "custom"
        type_key = data.get("type_key", self._type)
        self._del_btn.setEnabled(is_custom)
        self._save_changes_btn.setEnabled(False)
        self._editing_filename = data.get("filename", "") if is_custom else ""
        self._loading = True
        if is_custom:
            self._preview.setReadOnly(False)
            self._preview.setPlainText(data["content"])
        else:
            self._preview.setReadOnly(True)
            self._preview.setPlainText(
                _render_template_with_context(
                    self._app, type_key, data["content"])
            )
        self._loading = False

    def _on_content_changed(self):
        if self._loading:
            return
        if self._editing_filename:
            self._save_changes_btn.setEnabled(True)

    def _save_changes(self):
        if not self._editing_filename:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(_("Templates"))
        box.setText(_("Save changes to this template?"))
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.Yes)
        _localize_msgbox_buttons(box, _)
        if box.exec() != QMessageBox.Yes:
            return
        import os
        import json
        from templates import _custom_dir
        path = os.path.join(_custom_dir(), self._editing_filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["content"] = self._preview.toPlainText()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            QMessageBox.warning(self, "", str(exc))
            return
        self._save_changes_btn.setEnabled(False)
        item = self._list.currentItem()
        if item:
            d = item.data(Qt.UserRole)
            if d:
                d["content"] = self._preview.toPlainText()
                item.setData(Qt.UserRole, d)

    def _delete_selected(self):
        item = self._list.currentItem()
        if not item:
            return
        data = item.data(Qt.UserRole)
        if not data or data["kind"] != "custom":
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(_("Templates"))
        box.setText(_("Delete this template?"))
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        _localize_msgbox_buttons(box, _)
        if box.exec() != QMessageBox.Yes:
            return
        delete_custom_template(data["filename"])
        self._populate()

    def _create_new(self):
        dlg = CreateTemplateDialog(
            self._lang, self._type,
            prefill_content="",
            parent=self,
        )
        if dlg.exec() == QDialog.Accepted:
            self._populate()
            for i in range(self._list.count() - 1, -1, -1):
                d = self._list.item(i).data(Qt.UserRole)
                if d and d.get("kind") == "custom":
                    self._list.setCurrentRow(i)
                    break

    def _insert(self):
        item = self._list.currentItem()
        if not item:
            self.reject()
            return
        data = item.data(Qt.UserRole)
        if not data:
            self.reject()
            return
        raw_tpl = data["content"]
        type_key = data.get("type_key", self._type)
        self.chosen_content = _render_template_with_context(
            self._app, type_key, raw_tpl
        )
        self.accept()


class CreateTemplateDialog(QDialog):
    def __init__(self, lang: str, default_type: str = "daily",
                 prefill_content: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Create Custom Template"))
        self.setMinimumSize(520, 440)
        self.resize(580, 520)

        lv = QVBoxLayout(self)
        lv.setSpacing(8)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setSpacing(8)

        self._name = QLineEdit()
        self._name.setPlaceholderText(_("Template name"))
        form.addRow(_("Template name"), self._name)

        self._type_cb = QComboBox()
        for k, label in [("daily",   _("Daily")),
                         ("weekly",  _("Weekly")),
                         ("monthly", _("Monthly"))]:
            self._type_cb.addItem(label, k)
        idx = self._type_cb.findData(default_type)
        if idx >= 0:
            self._type_cb.setCurrentIndex(idx)
        form.addRow(_("Type"), self._type_cb)

        lv.addLayout(form)

        self._editor = QTextEdit()
        self._editor.setFont(QFont("monospace", 10))
        self._editor.setPlainText(prefill_content)
        lv.addWidget(self._editor, 1)

        btns = QDialogButtonBox(QDialogButtonBox.Save |
                                QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Save).setText(_("Save"))
        btns.button(QDialogButtonBox.Cancel).setText(_("Close"))
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        lv.addWidget(btns)

        self._lang = lang
        self.saved_filename: str = ""

    def _save(self):
        name = self._name.text().strip()
        if not name:
            self._name.setFocus()
            return
        self.saved_filename = save_custom_template(
            name, self._type_cb.currentData(), self._editor.toPlainText())
        QMessageBox.information(self, name, _("Template saved."))
        self.accept()
