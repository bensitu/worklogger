"""User management dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from worklogger.domain.shared.errors import AppError
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.viewmodels import (
    UserListItem,
    UserManagementState,
    UserManagementViewModel,
)
from worklogger.presentation.widgets import SwitchButton
from worklogger.presentation.widgets.assets import apply_window_icon


class UserManagementDialog(QDialog):
    def __init__(
        self,
        view_model: UserManagementViewModel,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._view_model = view_model
        self._users: dict[int, UserListItem] = {}
        self._last_error: AppError | None = None
        self.setObjectName("user_management_dialog")
        self.setWindowTitle(_("Manage users"))
        apply_window_icon(self)
        self._build_ui()

    @property
    def last_error(self) -> AppError | None:
        return self._last_error

    def refresh(self) -> bool:
        result = self._view_model.load()
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return False
        self.set_state(result.value)
        self.status_label.setText(_("Ready"))
        return True

    def set_state(self, state: UserManagementState) -> None:
        self._users = {item.user_id: item for item in state.users}
        self.user_table.setRowCount(len(state.users))
        for row, user in enumerate(state.users):
            username = QTableWidgetItem(user.username)
            username.setData(Qt.ItemDataRole.UserRole, user.user_id)
            role = QTableWidgetItem(_("Admin") if user.is_admin else _("User"))
            required = QTableWidgetItem(
                _("Required") if user.must_change_password else _("Not required")
            )
            for item in (username, role, required):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.user_table.setItem(row, 0, username)
            self.user_table.setItem(row, 1, role)
            self.user_table.setItem(row, 2, required)
        if state.users:
            self.user_table.selectRow(0)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        self.user_table = QTableWidget(0, 3)
        self.user_table.setHorizontalHeaderLabels(
            (_("Username"), _("Role"), _("Password change"))
        )
        self.user_table.horizontalHeader().setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.Stretch,
        )
        self.user_table.horizontalHeader().setSectionResizeMode(
            1,
            QHeaderView.ResizeMode.ResizeToContents,
        )
        self.user_table.horizontalHeader().setSectionResizeMode(
            2,
            QHeaderView.ResizeMode.ResizeToContents,
        )
        self.user_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.user_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        root.addWidget(self.user_table)

        actions = QHBoxLayout()
        self.toggle_required_button = QPushButton(_("Toggle password change"))
        self.reset_password_button = QPushButton(_("Reset password"))
        self.delete_user_button = QPushButton(_("Delete user"))
        actions.addWidget(self.toggle_required_button)
        actions.addWidget(self.reset_password_button)
        actions.addWidget(self.delete_user_button)
        root.addLayout(actions)

        root.addWidget(self._build_create_box())
        root.addWidget(self._build_reset_box())

        self.recovery_key_caption = QLabel(_("Recovery key"))
        self.recovery_key_caption.setObjectName("recovery_key_caption_label")
        self.recovery_key_label = QLabel("")
        self.recovery_key_label.setObjectName("recovery_key_label")
        self.recovery_key_label.setWordWrap(True)
        self.recovery_key_caption.setVisible(False)
        self.recovery_key_label.setVisible(False)
        root.addWidget(self.recovery_key_caption)
        root.addWidget(self.recovery_key_label)

        bottom = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setObjectName("user_management_status_label")
        self.close_button = QPushButton(_("Close"))
        self.close_button.setObjectName("close_user_management_button")
        self.close_button.setProperty("variant", "primary")
        bottom.addWidget(self.status_label, 1)
        bottom.addWidget(self.close_button)
        root.addLayout(bottom)

        self.create_user_button.clicked.connect(self._create_user)
        self.reset_password_button.clicked.connect(self._reset_password)
        self.toggle_required_button.clicked.connect(self._toggle_required)
        self.delete_user_button.clicked.connect(self._delete_selected)
        self.close_button.clicked.connect(self.accept)

    def _build_create_box(self) -> QGroupBox:
        box = QGroupBox(_("Create user"))
        form = QFormLayout(box)
        self.username_input = QLineEdit()
        self.create_password_input = QLineEdit()
        self.create_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.create_confirm_input = QLineEdit()
        self.create_confirm_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.create_admin_switch = SwitchButton()
        self.create_force_switch = SwitchButton()
        self.create_force_switch.set_checked(True)
        self.create_user_button = QPushButton(_("Create user"))
        self.create_user_button.setObjectName("create_user_button")
        self.create_user_button.setProperty("variant", "primary")
        form.addRow(_("Username"), self.username_input)
        form.addRow(_("Password"), self.create_password_input)
        form.addRow(_("Confirm password"), self.create_confirm_input)
        form.addRow(_("Admin"), _switch_row(self.create_admin_switch))
        form.addRow(_("Require password change"), _switch_row(self.create_force_switch))
        form.addRow("", self.create_user_button)
        return box

    def _build_reset_box(self) -> QGroupBox:
        box = QGroupBox(_("Reset selected user password"))
        form = QFormLayout(box)
        self.reset_password_input = QLineEdit()
        self.reset_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.reset_confirm_input = QLineEdit()
        self.reset_confirm_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.reset_force_switch = SwitchButton()
        self.reset_force_switch.set_checked(True)
        form.addRow(_("New password"), self.reset_password_input)
        form.addRow(_("Confirm password"), self.reset_confirm_input)
        form.addRow(_("Require password change"), _switch_row(self.reset_force_switch))
        return box

    def _create_user(self) -> None:
        result = self._view_model.create_user(
            username=self.username_input.text(),
            password=self.create_password_input.text(),
            password_confirm=self.create_confirm_input.text(),
            is_admin=self.create_admin_switch.is_checked(),
            must_change_password=self.create_force_switch.is_checked(),
        )
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return
        self._show_recovery_key(result.value.recovery_key)
        self.username_input.clear()
        self.create_password_input.clear()
        self.create_confirm_input.clear()
        self.refresh()
        self.status_label.setText(_("User created."))

    def _reset_password(self) -> None:
        user_id = self._selected_user_id()
        if user_id is None:
            self.status_label.setText(_("Select a user."))
            return
        result = self._view_model.reset_password(
            target_user_id=user_id,
            new_password=self.reset_password_input.text(),
            password_confirm=self.reset_confirm_input.text(),
            must_change_password=self.reset_force_switch.is_checked(),
        )
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return
        self._show_recovery_key(result.value)
        self.reset_password_input.clear()
        self.reset_confirm_input.clear()
        self.refresh()
        self.status_label.setText(_("Password reset."))

    def _toggle_required(self) -> None:
        user = self._selected_user()
        if user is None:
            self.status_label.setText(_("Select a user."))
            return
        result = self._view_model.set_password_change_required(
            target_user_id=user.user_id,
            required=not user.must_change_password,
        )
        if not result.ok:
            self._set_error(result.error)
            return
        self.refresh()
        self.status_label.setText(_("User updated."))

    def _delete_selected(self) -> None:
        user_id = self._selected_user_id()
        if user_id is None:
            self.status_label.setText(_("Select a user."))
            return
        result = self._view_model.delete_user(target_user_id=user_id)
        if not result.ok:
            self._set_error(result.error)
            return
        self.refresh()
        self.status_label.setText(_("User deleted."))

    def _selected_user_id(self) -> int | None:
        row = self.user_table.currentRow()
        if row < 0:
            return None
        item = self.user_table.item(row, 0)
        if item is None:
            return None
        raw_user_id = item.data(Qt.ItemDataRole.UserRole)
        return int(raw_user_id) if raw_user_id is not None else None

    def _selected_user(self) -> UserListItem | None:
        user_id = self._selected_user_id()
        return self._users.get(user_id) if user_id is not None else None

    def _show_recovery_key(self, recovery_key: str) -> None:
        self.recovery_key_label.setText(recovery_key)
        self.recovery_key_caption.setVisible(bool(recovery_key))
        self.recovery_key_label.setVisible(bool(recovery_key))

    def _set_error(self, error: AppError | None) -> None:
        self._last_error = error
        self.status_label.setText(display_error_message(error))


def _switch_row(switch: SwitchButton) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(switch)
    layout.addStretch(1)
    return row
