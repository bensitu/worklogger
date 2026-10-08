"""User management dialog."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSizePolicy,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
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
from worklogger.presentation.widgets.status_label import StatusLabel
from worklogger.presentation.widgets.icons import set_button_icon


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
        self._selection_id: int | None = None
        self.setObjectName("user_management_dialog")
        self.setWindowTitle(_("Manage users"))
        apply_window_icon(self)
        self._build_ui()
        self.resize(940, 600)
        self.setMinimumSize(860, 540)

    @property
    def last_error(self) -> AppError | None:
        return self._last_error

    def refresh(self) -> bool:
        result = self._view_model.load()
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return False
        self.set_state(result.value)
        self._last_error = None
        self.status_label.clear()
        return True

    def set_state(self, state: UserManagementState) -> None:
        selected_id = self._selected_user_id()
        self._users = {item.user_id: item for item in state.users}
        with QSignalBlocker(self.user_table):
            self.user_table.setRowCount(len(state.users))
            selected_row = 0
            for row, user in enumerate(state.users):
                username = QTableWidgetItem(user.username)
                username.setData(Qt.ItemDataRole.UserRole, user.user_id)
                role = QTableWidgetItem(_("Admin") if user.is_admin else _("User"))
                required = QTableWidgetItem(_("Required") if user.must_change_password else _("Not required"))
                for item in (username, role, required):
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.user_table.setItem(row, 0, username)
                self.user_table.setItem(row, 1, role)
                self.user_table.setItem(row, 2, required)
                if user.user_id == selected_id:
                    selected_row = row
            if state.users:
                self.user_table.selectRow(selected_row)
            else:
                self.user_table.setCurrentCell(-1, -1)
        self._sync_selected_user()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        root.setSpacing(16)
        body = QHBoxLayout()
        body.setSpacing(20)
        users = QVBoxLayout()
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel(_("Manage users")), 1)
        self.new_user_button = QPushButton(_("Create user"))
        set_button_icon(self.new_user_button, "plus")
        toolbar.addWidget(self.new_user_button)
        users.addLayout(toolbar)

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
        self.user_table.verticalHeader().hide()
        self.user_table.setShowGrid(False)
        self.user_table.setAlternatingRowColors(True)
        self.user_table.verticalHeader().setDefaultSectionSize(36)
        users.addWidget(self.user_table, 1)
        body.addLayout(users, 1)
        self.operation_tabs = QTabWidget()
        self.operation_tabs.setMinimumWidth(390)
        self.selected_user_page = self._build_selected_user_page()
        self.operation_tabs.addTab(self.selected_user_page, _("Selected user"))
        self.operation_tabs.addTab(self._build_create_box(), _("Create user"))
        body.addWidget(self.operation_tabs, 1)
        root.addLayout(body, 1)

        self.recovery_key_caption = QLabel(_("Recovery key"))
        self.recovery_key_caption.setObjectName("recovery_key_caption_label")
        self.recovery_key_label = QLabel("")
        self.recovery_key_label.setObjectName("recovery_key_label")
        self.recovery_key_label.setWordWrap(True)
        self.recovery_key_caption.setVisible(False)
        self.recovery_key_label.setVisible(False)
        self.recovery_key_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.credential_layout.addWidget(self.recovery_key_caption)
        self.credential_layout.addWidget(self.recovery_key_label)

        bottom = QHBoxLayout()
        self.status_label = StatusLabel()
        self.status_label.setObjectName("user_management_status_label")
        self.close_button = QPushButton(_("Close"))
        self.close_button.setObjectName("close_user_management_button")
        self.close_button.setProperty("variant", "primary")
        bottom.addWidget(self.status_label, 1)
        bottom.addStretch()
        bottom.addWidget(self.close_button)
        root.addLayout(bottom)

        self.create_user_button.clicked.connect(self._create_user)
        self.reset_password_button.clicked.connect(self._reset_password)
        self.password_change_checkbox.clicked.connect(self._toggle_required)
        self.delete_user_button.clicked.connect(self._delete_selected)
        self.close_button.clicked.connect(self.accept)
        self.user_table.itemSelectionChanged.connect(self._sync_selected_user)
        self.user_table.cellClicked.connect(lambda _row, _column: self.operation_tabs.setCurrentIndex(0))
        self.operation_tabs.currentChanged.connect(self._operation_changed)
        self.new_user_button.clicked.connect(self._show_create_user)
        for button in (self.new_user_button, self.create_user_button, self.reset_password_button,
                       self.delete_user_button, self.close_button):
            button.setMinimumHeight(36)
            button.setAutoDefault(False)
        self._sync_selected_user()

    def _build_selected_user_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        self.selected_user_label = QLabel(_("Select a user."))
        self.selected_user_label.setWordWrap(True)
        self.selected_user_label.setStyleSheet("font-size: 18px; font-weight: 600;")
        heading = QHBoxLayout()
        heading.addWidget(self.selected_user_label, 1)
        self.selected_role_label = QLabel()
        self.selected_role_label.setProperty("role", "secondary")
        heading.addWidget(self.selected_role_label)
        layout.addLayout(heading)
        self.password_change_checkbox = QCheckBox(_("Require password change"))
        layout.addWidget(self.password_change_checkbox)
        layout.addWidget(self._build_reset_box())
        self.credential_layout = QVBoxLayout()
        self.credential_layout.setSpacing(6)
        layout.addLayout(self.credential_layout)
        layout.addStretch(1)
        self.delete_user_button = QPushButton(_("Delete user"))
        set_button_icon(self.delete_user_button, "trash")
        layout.addWidget(self.delete_user_button, 0, Qt.AlignmentFlag.AlignRight)
        return page

    def _build_create_box(self) -> QWidget:
        box = QWidget()
        form = QFormLayout(box)
        form.setContentsMargins(16, 16, 16, 16)
        form.setSpacing(12)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
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
        set_button_icon(self.create_user_button, "user-round")
        form.addRow(_("Username"), self.username_input)
        form.addRow(_("Password"), self.create_password_input)
        form.addRow(_("Confirm password"), self.create_confirm_input)
        form.addRow(_("Admin"), _switch_row(self.create_admin_switch))
        form.addRow(_("Require password change"), _switch_row(self.create_force_switch))
        form.addRow("", self.create_user_button)
        return box

    def _build_reset_box(self) -> QWidget:
        box = QWidget()
        box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)
        form = QFormLayout()
        form.setSpacing(12)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.reset_password_input = QLineEdit()
        self.reset_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.reset_confirm_input = QLineEdit()
        self.reset_confirm_input.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(_("New password"), self.reset_password_input)
        form.addRow(_("Confirm password"), self.reset_confirm_input)
        hint = QLabel(_("Password changes are required after a reset."))
        hint.setProperty("role", "secondary")
        hint.setWordWrap(True)
        form.addRow(hint)
        layout.addLayout(form)
        self.reset_password_button = QPushButton(_("Reset password"))
        self.reset_password_button.setProperty("variant", "primary")
        set_button_icon(self.reset_password_button, "lock-keyhole")
        layout.addWidget(self.reset_password_button)
        return box

    def _show_create_user(self) -> None:
        self.operation_tabs.setCurrentIndex(1)
        self.username_input.setFocus()

    def _operation_changed(self, index: int) -> None:
        if index == 1:
            self.username_input.setFocus()

    def _sync_selected_user(self) -> None:
        user = self._selected_user()
        user_id = user.user_id if user else None
        if user_id != self._selection_id:
            self.reset_password_input.clear()
            self.reset_confirm_input.clear()
            self.recovery_key_caption.hide()
            self.recovery_key_label.clear()
            self.recovery_key_label.hide()
            if user is not None:
                self.operation_tabs.setCurrentIndex(0)
        self._selection_id = user_id
        self.selected_user_label.setText(user.username if user else _("Select a user."))
        self.selected_role_label.setText((_("Admin") if user.is_admin else _("User")) if user else "")
        with QSignalBlocker(self.password_change_checkbox):
            self.password_change_checkbox.setChecked(bool(user and user.must_change_password))
        for widget in (self.password_change_checkbox, self.reset_password_input,
                       self.reset_confirm_input, self.reset_password_button, self.delete_user_button):
            widget.setEnabled(user is not None)

    def _select_user(self, user_id: int) -> None:
        for row in range(self.user_table.rowCount()):
            if self.user_table.item(row, 0).data(Qt.ItemDataRole.UserRole) == user_id:
                self.user_table.selectRow(row)
                break

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
        self.username_input.clear()
        self.create_password_input.clear()
        self.create_confirm_input.clear()
        self.refresh()
        self._select_user(result.value.user.id)
        self.operation_tabs.setCurrentIndex(0)
        self._show_recovery_key(result.value.recovery_key)
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
            must_change_password=True,
        )
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return
        self.reset_password_input.clear()
        self.reset_confirm_input.clear()
        self.refresh()
        self._show_recovery_key(result.value)
        self.recovery_key_caption.setText(_("Temporary password"))
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
            self._sync_selected_user()
            return
        self.refresh()
        self.status_label.setText(_("User updated."))

    def _delete_selected(self) -> None:
        user = self._selected_user()
        if user is None:
            self.status_label.setText(_("Select a user."))
            return
        if QMessageBox.question(self, _("Delete user"),
            _("Delete user {username} and their data?").format(username=user.username),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        result = self._view_model.delete_user(target_user_id=user.user_id)
        if not result.ok:
            self._set_error(result.error)
            return
        self.refresh()
        self.status_label.setText(_("User deleted."))

    def _selected_user_id(self) -> int | None:
        selected = self.user_table.selectionModel().selectedRows()
        if not selected:
            return None
        row = selected[0].row()
        item = self.user_table.item(row, 0)
        if item is None:
            return None
        raw_user_id = item.data(Qt.ItemDataRole.UserRole)
        return int(raw_user_id) if raw_user_id is not None else None

    def _selected_user(self) -> UserListItem | None:
        user_id = self._selected_user_id()
        return self._users.get(user_id) if user_id is not None else None

    def _show_recovery_key(self, recovery_key: str) -> None:
        self.recovery_key_caption.setText(_("Recovery key"))
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
