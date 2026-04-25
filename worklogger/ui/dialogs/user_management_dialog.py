from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from utils.i18n import _


class _AdminPasswordDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.admin_password = ""

        self.setWindowTitle(_("Confirm Administrator Password"))
        self.setMinimumWidth(360)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(_("Administrator Password"), self._password)
        root.addLayout(form)

        row = QHBoxLayout()
        cancel_btn = QPushButton(_("Cancel"))
        ok_btn = QPushButton(_("OK"))
        ok_btn.setObjectName("primary_btn")
        row.addStretch()
        row.addWidget(cancel_btn)
        row.addWidget(ok_btn)
        root.addLayout(row)

        cancel_btn.clicked.connect(self.reject)
        ok_btn.clicked.connect(self._accept)
        self._password.returnPressed.connect(self._accept)

    def _accept(self) -> None:
        self.admin_password = self._password.text()
        if not self.admin_password:
            QMessageBox.warning(
                self,
                _("Confirm Administrator Password"),
                _("Please enter administrator password."),
            )
            return
        self.accept()


class _AdminResetPasswordDialog(QDialog):
    def __init__(self, username: str, parent=None):
        super().__init__(parent)
        self.admin_password = ""
        self.new_password = ""
        self.clear_remember = True

        self.setWindowTitle(_("Reset User Password"))
        self.setMinimumWidth(400)
        root = QVBoxLayout(self)
        form = QFormLayout()
        user = QLineEdit(username)
        user.setReadOnly(True)
        self._admin_password = QLineEdit()
        self._new = QLineEdit()
        self._confirm = QLineEdit()
        for edit in (self._admin_password, self._new, self._confirm):
            edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(_("Username"), user)
        form.addRow(_("Administrator Password"), self._admin_password)
        form.addRow(_("New Password"), self._new)
        form.addRow(_("Confirm Password"), self._confirm)
        root.addLayout(form)

        self._clear_remember = QCheckBox(_("Sign out remembered sessions"))
        self._clear_remember.setChecked(True)
        root.addWidget(self._clear_remember)

        row = QHBoxLayout()
        cancel_btn = QPushButton(_("Cancel"))
        reset_btn = QPushButton(_("Reset Password"))
        reset_btn.setObjectName("primary_btn")
        row.addStretch()
        row.addWidget(cancel_btn)
        row.addWidget(reset_btn)
        root.addLayout(row)

        cancel_btn.clicked.connect(self.reject)
        reset_btn.clicked.connect(self._accept)
        self._confirm.returnPressed.connect(self._accept)

    def _accept(self) -> None:
        admin_password = self._admin_password.text()
        new_password = self._new.text()
        confirm = self._confirm.text()
        if not admin_password:
            QMessageBox.warning(
                self,
                _("Reset User Password"),
                _("Please enter administrator password."),
            )
            return
        if len(new_password) < 6:
            QMessageBox.warning(
                self,
                _("Reset User Password"),
                _("Password must be at least 6 characters."),
            )
            return
        if new_password != confirm:
            QMessageBox.warning(
                self,
                _("Reset User Password"),
                _("Passwords do not match."),
            )
            return
        self.admin_password = admin_password
        self.new_password = new_password
        self.clear_remember = self._clear_remember.isChecked()
        self.accept()


class UserManagementDialog(QDialog):
    def __init__(self, services, parent=None):
        super().__init__(parent)
        self._services = services
        self._users: list[dict] = []

        self.setWindowTitle(_("Manage Users"))
        self.setMinimumSize(560, 360)

        root = QVBoxLayout(self)
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(
            [_("Username"), _("Role"), _("Recovery Key"), _("Password Changed")]
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self._table, 1)

        row = QHBoxLayout()
        self._reset_btn = QPushButton(_("Reset Password"))
        self._admin_btn = QPushButton(_("Grant Admin"))
        refresh_btn = QPushButton(_("Refresh"))
        close_btn = QPushButton(_("Close"))
        row.addWidget(self._reset_btn)
        row.addWidget(self._admin_btn)
        row.addStretch()
        row.addWidget(refresh_btn)
        row.addWidget(close_btn)
        root.addLayout(row)

        self._table.itemSelectionChanged.connect(self._sync_buttons)
        self._reset_btn.clicked.connect(self._reset_password)
        self._admin_btn.clicked.connect(self._toggle_admin)
        refresh_btn.clicked.connect(self._refresh)
        close_btn.clicked.connect(self.accept)
        self._refresh()

    def _refresh(self) -> None:
        try:
            self._users = self._services.list_users_for_management()
        except PermissionError:
            QMessageBox.warning(
                self,
                _("Manage Users"),
                _("Administrator privileges are required."),
            )
            self.reject()
            return
        self._table.setRowCount(len(self._users))
        for row, user in enumerate(self._users):
            values = [
                user["username"],
                _("Administrator") if user.get("is_admin") else _("User"),
                _("Yes") if user.get("has_recovery_key") else _("No"),
                str(user.get("password_changed_at") or ""),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, int(user["id"]))
                self._table.setItem(row, col, item)
        self._table.resizeColumnsToContents()
        self._sync_buttons()

    def _selected_user(self) -> dict | None:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._users):
            return None
        return self._users[row]

    def _sync_buttons(self) -> None:
        user = self._selected_user()
        has_user = user is not None
        self._reset_btn.setEnabled(has_user)
        self._admin_btn.setEnabled(has_user)
        if user and user.get("is_admin"):
            self._admin_btn.setText(_("Revoke Admin"))
        else:
            self._admin_btn.setText(_("Grant Admin"))

    def _reset_password(self) -> None:
        user = self._selected_user()
        if not user:
            return
        dlg = _AdminResetPasswordDialog(user["username"], self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            changed = self._services.admin_reset_password(
                dlg.admin_password,
                int(user["id"]),
                dlg.new_password,
                clear_remember=dlg.clear_remember,
            )
        except ValueError as exc:
            self._show_admin_error(str(exc))
            return
        except PermissionError:
            QMessageBox.warning(
                self,
                _("Manage Users"),
                _("Administrator privileges are required."),
            )
            return
        if not changed:
            QMessageBox.warning(
                self,
                _("Manage Users"),
                _("User not found."),
            )
            return
        QMessageBox.information(
            self,
            _("Manage Users"),
            _("Password reset successfully."),
        )
        self._refresh()

    def _toggle_admin(self) -> None:
        user = self._selected_user()
        if not user:
            return
        enable = not bool(user.get("is_admin"))
        dlg = _AdminPasswordDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            changed = self._services.set_user_admin(
                dlg.admin_password,
                int(user["id"]),
                enable,
            )
        except ValueError as exc:
            self._show_admin_error(str(exc))
            return
        except PermissionError:
            QMessageBox.warning(
                self,
                _("Manage Users"),
                _("Administrator privileges are required."),
            )
            return
        if not changed:
            QMessageBox.warning(
                self,
                _("Manage Users"),
                _("User not found."),
            )
            return
        self._refresh()

    def _show_admin_error(self, code: str) -> None:
        if code == "admin_password_incorrect":
            text = _("Administrator password is incorrect.")
        elif code == "last_admin":
            text = _("At least one administrator account is required.")
        elif code == "password_too_short":
            text = _("Password must be at least 6 characters.")
        else:
            text = _("Operation failed.")
        QMessageBox.warning(self, _("Manage Users"), text)
