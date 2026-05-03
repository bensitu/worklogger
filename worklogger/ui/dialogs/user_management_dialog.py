from __future__ import annotations

from functools import partial
from datetime import datetime, timezone
from turtle import color

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config.themes import dialog_title_qss, user_dialog_button_qss, user_table_qss
from config.constants import (
    PASSWORD_MIN_LENGTH,
    USER_INITIAL_PASSWORD_FILENAME_PREFIX,
    USER_MANAGEMENT_ACTION_COLUMN,
    USER_MANAGEMENT_ACTION_COLUMN_WIDTH,
    USER_MANAGEMENT_COLUMN_COUNT,
    USER_MANAGEMENT_ROW_HEIGHT,
)
from utils.formatters import format_timestamp_for_display
from utils.i18n import _, msg
from ui.widgets import SwitchButton
from .common import _localize_msgbox_buttons


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

        hint = QLabel(msg("change_password_recovery_key_warning"))
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        root.addWidget(hint)

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

        clear_row = QWidget()
        clear_layout = QHBoxLayout(clear_row)
        clear_layout.setContentsMargins(0, 0, 0, 0)
        clear_layout.setSpacing(8)
        self._clear_remember = SwitchButton(checked=True)
        clear_layout.addWidget(self._clear_remember)
        clear_layout.addWidget(QLabel(_("Sign out remembered sessions")))
        clear_layout.addStretch()
        root.addWidget(clear_row)

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
        if len(new_password) < PASSWORD_MIN_LENGTH:
            QMessageBox.warning(
                self,
                _("Reset User Password"),
                _("Password must be at least 8 characters."),
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


class _CreateUserDialog(QDialog):
    def __init__(self, services, parent=None):
        super().__init__(parent)
        self._services = services
        self.username = ""
        self.admin_password = ""
        self.initial_password = self._generate_password()

        self.setWindowTitle(_("Create User"))
        self.setMinimumWidth(440)
        root = QVBoxLayout(self)

        hint = QLabel(
            _(
                "The initial password is generated automatically. "
                "The user must change it at first login."
            )
        )
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        root.addWidget(hint)

        form = QFormLayout()
        self._username = QLineEdit()
        self._initial_password = QLineEdit(self.initial_password)
        self._initial_password.setReadOnly(True)
        self._admin_password = QLineEdit()
        self._admin_password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(_("Username"), self._username)
        form.addRow(_("Initial Password"), self._initial_password)
        form.addRow(_("Administrator Password"), self._admin_password)
        root.addLayout(form)

        row = QHBoxLayout()
        regenerate_btn = QPushButton(_("Regenerate"))
        cancel_btn = QPushButton(_("Cancel"))
        create_btn = QPushButton(_("Create User"))
        create_btn.setObjectName("primary_btn")
        row.addWidget(regenerate_btn)
        row.addStretch()
        row.addWidget(cancel_btn)
        row.addWidget(create_btn)
        root.addLayout(row)

        regenerate_btn.clicked.connect(self._regenerate_password)
        cancel_btn.clicked.connect(self.reject)
        create_btn.clicked.connect(self._accept)
        self._admin_password.returnPressed.connect(self._accept)

    def _generate_password(self) -> str:
        try:
            return self._services.generate_initial_password()
        except Exception:
            return ""

    def _regenerate_password(self) -> None:
        self.initial_password = self._generate_password()
        self._initial_password.setText(self.initial_password)

    def _accept(self) -> None:
        username = self._username.text().strip()
        admin_password = self._admin_password.text()
        if not username:
            QMessageBox.warning(
                self,
                _("Create User"),
                _("Username is required."),
            )
            return
        if len(self.initial_password) < PASSWORD_MIN_LENGTH:
            QMessageBox.warning(
                self,
                _("Create User"),
                _("Password must be at least 8 characters."),
            )
            return
        if not admin_password:
            QMessageBox.warning(
                self,
                _("Create User"),
                _("Please enter administrator password."),
            )
            return
        self.username = username
        self.admin_password = admin_password
        self.accept()


class _DeleteUserDialog(QDialog):
    def __init__(self, username: str, parent=None):
        super().__init__(parent)
        self.admin_password = ""

        self.setWindowTitle(msg("delete_user"))
        self.setMinimumWidth(440)
        root = QVBoxLayout(self)

        warning = QLabel(msg("delete_user_warning"))
        warning.setWordWrap(True)
        root.addWidget(warning)

        detail = QLabel(
            msg("confirm_admin_password_to_delete_user", username=username)
        )
        detail.setWordWrap(True)
        root.addWidget(detail)

        form = QFormLayout()
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(_("Administrator Password"), self._password)
        root.addLayout(form)

        row = QHBoxLayout()
        cancel_btn = QPushButton(_("Cancel"))
        delete_btn = QPushButton(msg("delete_user"))
        delete_btn.setObjectName("danger_btn")
        row.addStretch()
        row.addWidget(cancel_btn)
        row.addWidget(delete_btn)
        root.addLayout(row)

        cancel_btn.clicked.connect(self.reject)
        delete_btn.clicked.connect(self._accept)
        self._password.returnPressed.connect(self._accept)

    def _accept(self) -> None:
        self.admin_password = self._password.text()
        if not self.admin_password:
            QMessageBox.warning(
                self,
                msg("delete_user"),
                _("Please enter administrator password."),
            )
            return
        self.accept()


class UserManagementDialog(QDialog):
    def __init__(
        self,
        services,
        *,
        theme_name: str = "blue",
        dark: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._services = services
        self._users: list[dict] = []
        self._theme_name = theme_name
        self._dark = bool(dark)

        self.setWindowTitle(_("Manage Users"))
        self.setMinimumSize(1100, 460)
        self.resize(1175, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel(_("Manage Users"))
        title.setStyleSheet(dialog_title_qss())
        subtitle = QLabel(
            _("Review accounts, reset passwords, and manage recovery keys.")
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("muted")
        root.addWidget(title)
        root.addWidget(subtitle)

        self._table = QTableWidget(0, USER_MANAGEMENT_COLUMN_COUNT)
        self._table.setHorizontalHeaderLabels(
            [
                _("#"),
                _("Username"),
                _("Role"),
                _("In Use"),
                _("Recovery Key"),
                _("Created"),
                _("Password Changed"),
                _("Recovery Key Created"),
                _("Actions"),
            ]
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(
            USER_MANAGEMENT_ACTION_COLUMN,
            QHeaderView.ResizeMode.Fixed,
        )
        self._table.setColumnWidth(
            USER_MANAGEMENT_ACTION_COLUMN,
            USER_MANAGEMENT_ACTION_COLUMN_WIDTH,
        )
        root.addWidget(self._table, 1)

        footer = QHBoxLayout()
        self._create_btn = QPushButton(_("Create User"))
        self._refresh_btn = QPushButton(_("Refresh"))
        close_btn = QPushButton(_("Close"))
        self._create_btn.setObjectName("primary_btn")
        footer.addWidget(self._create_btn)
        footer.addStretch()
        footer.addWidget(self._refresh_btn)
        footer.addWidget(close_btn)
        root.addLayout(footer)

        self._create_btn.clicked.connect(self._create_user)
        self._refresh_btn.clicked.connect(self._refresh)
        close_btn.clicked.connect(self.accept)
        self._apply_theme_styles()
        self._refresh()

    def _apply_theme_styles(self) -> None:
        self._table.setStyleSheet(user_table_qss(self._dark, self._theme_name))
        self.setStyleSheet(
            self.styleSheet()
            + user_dialog_button_qss(self._dark, self._theme_name)
        )

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
                str(row + 1),
                user.get("username", ""),
                _("Administrator") if user.get("is_admin") else _("User"),
                _("Used") if user.get("is_used") else _("Unused"),
                _("Yes") if user.get("has_recovery_key") else _("No"),
                self._format_timestamp(user.get("created_at")),
                self._format_timestamp(user.get("password_changed_at")),
                self._format_timestamp(user.get("recovery_key_created_at")),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setData(Qt.ItemDataRole.UserRole, int(user["id"]))
                self._table.setItem(row, col, item)
            self._table.setCellWidget(
                row,
                USER_MANAGEMENT_ACTION_COLUMN,
                self._actions_widget(user),
            )
            self._table.setRowHeight(row, USER_MANAGEMENT_ROW_HEIGHT)
        self._table.resizeColumnsToContents()
        self._table.horizontalHeader().setSectionResizeMode(
            USER_MANAGEMENT_ACTION_COLUMN,
            QHeaderView.ResizeMode.Fixed,
        )
        self._table.setColumnWidth(
            USER_MANAGEMENT_ACTION_COLUMN,
            USER_MANAGEMENT_ACTION_COLUMN_WIDTH,
        )

    @staticmethod
    def _format_timestamp(raw) -> str:
        return format_timestamp_for_display(str(raw or ""))

    def _actions_widget(self, user: dict) -> QWidget:
        wrap = QWidget()
        wrap.setObjectName("transparent_container")
        wrap.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        wrap.setStyleSheet(
            "QWidget#transparent_container{"
            "background:transparent;background-color:transparent;border:none;"
            "}"
        )
        layout = QHBoxLayout(wrap)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(6)

        reset_btn = QPushButton(_("Reset Password"))
        admin_btn = QPushButton(
            _("Revoke Admin") if user.get("is_admin") else _("Grant Admin")
        )
        regen_btn = QPushButton(_("Regenerate Key"))
        delete_btn = QPushButton(msg("delete_user"))
        reset_btn.setObjectName("primary_btn")
        delete_btn.setObjectName("danger_btn")
        regen_btn.setEnabled(not bool(user.get("is_admin")))
        reset_btn.setMinimumWidth(120)
        admin_btn.setMinimumWidth(110)
        regen_btn.setMinimumWidth(135)
        delete_btn.setMinimumWidth(95)
        for button in (reset_btn, admin_btn, regen_btn, delete_btn):
            button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        regen_btn.setToolTip(_("Regenerate Recovery Key"))

        reset_btn.clicked.connect(partial(self._reset_password, user))
        admin_btn.clicked.connect(partial(self._toggle_admin, user))
        regen_btn.clicked.connect(partial(self._regenerate_recovery_key, user))
        delete_btn.clicked.connect(partial(self._delete_user, user))

        layout.addWidget(reset_btn)
        layout.addWidget(admin_btn)
        layout.addWidget(regen_btn)
        if not bool(user.get("is_admin")):
            layout.addWidget(delete_btn)
        layout.addStretch()
        return wrap

    def _create_user(self) -> None:
        dlg = _CreateUserDialog(self._services, self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            _user_id, initial_password = self._services.create_user_by_admin(
                dlg.admin_password,
                dlg.username,
                dlg.initial_password,
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
        self._show_initial_password(dlg.username, initial_password)
        self._refresh()

    def _show_initial_password(self, username: str, initial_password: str) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle(_("Create User"))
        dlg.setMinimumWidth(460)
        root = QVBoxLayout(dlg)

        info = QLabel(
            _(
                "User created successfully. Share this initial password now; "
                "it cannot be shown again later."
            )
        )
        info.setWordWrap(True)
        root.addWidget(info)

        form = QFormLayout()
        username_edit = QLineEdit(username)
        username_edit.setReadOnly(True)
        password_edit = QLineEdit(initial_password)
        password_edit.setReadOnly(True)
        password_edit.setStyleSheet("color:#cccccc;")
        form.addRow(_("Username"), username_edit)
        form.addRow(_("Initial Password"), password_edit)
        root.addLayout(form)

        note = QLabel(
            _("The user must change this password at first login.")
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        root.addWidget(note)

        status_lbl = QLabel("")
        status_lbl.setObjectName("muted")
        root.addWidget(status_lbl)

        row = QHBoxLayout()
        copy_btn = QPushButton(_("Copy"))
        save_as_btn = QPushButton(_("Save As"))
        ok_btn = QPushButton(_("OK"))
        ok_btn.setObjectName("primary_btn")
        row.addStretch()
        row.addWidget(copy_btn)
        row.addWidget(save_as_btn)
        row.addWidget(ok_btn)
        root.addLayout(row)

        def _copy_password() -> None:
            QApplication.clipboard().setText(initial_password)
            status_lbl.setText(_("Copied!"))

        def _save_password() -> None:
            safe_username = "".join(
                ch if ch.isalnum() or ch in "-_" else "_"
                for ch in username
            ) or "user"
            path, _dialog_filter = QFileDialog.getSaveFileName(
                dlg,
                _("Save Initial Password"),
                f"{USER_INITIAL_PASSWORD_FILENAME_PREFIX}-{safe_username}.txt",
                _("Text Files (*.txt)"),
            )
            if not path:
                return
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(f"{_('Username')}: {username}\n")
                    fh.write(f"{_('Initial Password')}: {initial_password}\n")
                    fh.write("\n")
                    fh.write(f"{_('Note')}: {_('The user must change this password at first login.')}\n")
            except OSError:
                QMessageBox.warning(
                    dlg,
                    _("Create User"),
                    _("Could not save initial password."),
                )
                return
            status_lbl.setText(_("Initial password saved."))

        copy_btn.clicked.connect(_copy_password)
        save_as_btn.clicked.connect(_save_password)
        ok_btn.clicked.connect(dlg.accept)
        dlg.exec()

    def _reset_password(self, user: dict) -> None:
        dlg = _AdminResetPasswordDialog(user.get("username", ""), self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            new_recovery_key = self._services.admin_reset_password(
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
        if not new_recovery_key:
            QMessageBox.warning(
                self,
                _("Manage Users"),
                _("User not found."),
            )
            return
        self._show_recovery_key(str(user.get("username", "")), new_recovery_key)
        self._refresh()

    def _toggle_admin(self, user: dict) -> None:
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

    def _regenerate_recovery_key(self, user: dict) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(_("Regenerate Recovery Key"))
        box.setText(
            _(
                "Are you sure you want to regenerate the recovery key? "
                "The old key will stop working immediately."
            )
        )
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        box.setDefaultButton(QMessageBox.StandardButton.No)
        _localize_msgbox_buttons(box, _)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        try:
            key = self._services.regenerate_recovery_key(
                str(user.get("username", "")),
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
        self._show_recovery_key(str(user.get("username", "")), key)
        self._refresh()

    def _delete_user(self, user: dict) -> None:
        username = str(user.get("username", ""))
        dlg = _DeleteUserDialog(username, self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            deleted = self._services.delete_user_by_admin(
                dlg.admin_password,
                username,
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
        if not deleted:
            QMessageBox.warning(
                self,
                _("Manage Users"),
                _("User not found."),
            )
            return
        QMessageBox.information(
            self,
            _("Manage Users"),
            msg("delete_user_success"),
        )
        self._refresh()

    def _show_recovery_key(self, username: str, recovery_key: str) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle(_("Recovery Key Regenerated"))
        dlg.setMinimumWidth(460)
        generated_at = format_timestamp_for_display(
            datetime.now(timezone.utc).isoformat(timespec="seconds")
        )
        note_text = _(
            "This recovery key can be used to reset the user's password if it is forgotten. "
            "Store it securely and share it only with the account owner. "
            "Anyone with this key may reset the password until a new key is generated."
        )
        root = QVBoxLayout(dlg)
        info = QLabel(
            _(
                "A new recovery key was generated. Share it with the user now; "
                "it cannot be shown again later."
            )
        )
        info.setWordWrap(True)
        root.addWidget(info)
        form = QFormLayout()
        username_edit = QLineEdit(username)
        username_edit.setReadOnly(True)
        key_edit = QLineEdit(recovery_key)
        key_edit.setReadOnly(True)
        form.addRow(_("Username"), username_edit)
        generated_edit = QLineEdit(generated_at)
        generated_edit.setReadOnly(True)
        form.addRow(_("Generated At"), generated_edit)
        form.addRow(_("Recovery Key"), key_edit)
        root.addLayout(form)

        status_lbl = QLabel("")
        status_lbl.setObjectName("muted")
        root.addWidget(status_lbl)

        row = QHBoxLayout()
        copy_btn = QPushButton(_("Copy"))
        save_as_btn = QPushButton(_("Save As"))
        ok_btn = QPushButton(_("OK"))
        ok_btn.setObjectName("primary_btn")
        row.addStretch()
        row.addWidget(copy_btn)
        row.addWidget(save_as_btn)
        row.addWidget(ok_btn)
        root.addLayout(row)

        def _copy_key() -> None:
            QApplication.clipboard().setText(recovery_key)
            status_lbl.setText(_("Copied!"))

        def _save_key() -> None:
            safe_username = "".join(
                ch if ch.isalnum() or ch in "-_" else "_"
                for ch in username
            ) or "user"
            path, _dialog_filter = QFileDialog.getSaveFileName(
                dlg,
                _("Save Recovery Key"),
                f"worklogger-recovery-key-{safe_username}.txt",
                _("Text Files (*.txt)"),
            )
            if not path:
                return
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(f"{_('Username')}: {username}\n")
                    fh.write(f"{_('Generated At')}: {generated_at}\n")
                    fh.write(f"{_('Recovery Key')}: {recovery_key}\n")
                    fh.write("\n")
                    fh.write(f"{_('Note')}: {note_text}\n")
            except OSError:
                QMessageBox.warning(
                    dlg,
                    _("Recovery Key Regenerated"),
                    _("Could not save recovery key."),
                )
                return
            status_lbl.setText(_("Recovery key saved."))

        copy_btn.clicked.connect(_copy_key)
        save_as_btn.clicked.connect(_save_key)
        ok_btn.clicked.connect(dlg.accept)
        dlg.exec()

    def _show_admin_error(self, code: str) -> None:
        if code == "admin_password_incorrect":
            text = msg("admin_password_incorrect")
        elif code == "cannot_delete_admin":
            text = msg("cannot_delete_admin")
        elif code == "last_admin":
            text = _("At least one administrator account is required.")
        elif code == "password_too_short":
            text = _("Password must be at least 8 characters.")
        elif code == "username_required":
            text = _("Username is required.")
        elif code == "username_exists":
            text = _("Username already exists.")
        elif code == "user_not_found":
            text = _("User not found.")
        else:
            text = _("Operation failed.")
        QMessageBox.warning(self, _("Manage Users"), text)
