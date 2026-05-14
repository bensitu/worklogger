from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from tests.app.test_user_management_use_cases import MemoryAuthRepository
from worklogger.app.commands.auth_commands import RegisterUserCommand
from worklogger.app.use_cases.auth import (
    AdminResetPasswordHandler,
    CreateManagedUserHandler,
    DeleteManagedUserHandler,
    ListUsersHandler,
    RegisterUserHandler,
    SetPasswordChangeRequiredHandler,
)
from worklogger.presentation.user_management import UserManagementDialog
from worklogger.presentation.viewmodels import UserManagementViewModel


def _app() -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        return existing
    return QApplication([])


def _view_model(
    repository: MemoryAuthRepository,
    requesting_user_id: int,
) -> UserManagementViewModel:
    return UserManagementViewModel(
        requesting_user_id=requesting_user_id,
        list_users_handler=ListUsersHandler(repository),
        create_user_handler=CreateManagedUserHandler(repository),
        reset_password_handler=AdminResetPasswordHandler(repository),
        set_password_change_required_handler=SetPasswordChangeRequiredHandler(repository),
        delete_user_handler=DeleteManagedUserHandler(repository),
    )


class UserManagementPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = _app()

    def test_viewmodel_rejects_password_mismatch_before_handler_call(self) -> None:
        repository = MemoryAuthRepository()
        admin = RegisterUserHandler(repository).handle(
            RegisterUserCommand("admin", "secret123")
        )
        assert admin.value is not None
        view_model = _view_model(repository, admin.value.user.id)

        result = view_model.create_user(
            username="bob",
            password="secret456",
            password_confirm="different",
            is_admin=False,
            must_change_password=True,
        )

        self.assertFalse(result.ok)
        self.assertEqual(
            result.error.code if result.error else "",
            "managed_user_password_mismatch",
        )

    def test_dialog_creates_resets_toggles_and_deletes_user(self) -> None:
        repository = MemoryAuthRepository()
        admin = RegisterUserHandler(repository).handle(
            RegisterUserCommand("admin", "secret123")
        )
        assert admin.value is not None
        dialog = UserManagementDialog(_view_model(repository, admin.value.user.id))
        self.assertTrue(dialog.refresh())

        dialog.username_input.setText("bob")
        dialog.create_password_input.setText("secret456")
        dialog.create_confirm_input.setText("secret456")
        dialog.create_user_button.click()

        self.assertIsNotNone(repository.get_by_username("bob"))
        self.assertEqual(dialog.user_table.rowCount(), 2)
        self.assertFalse(dialog.recovery_key_label.isHidden())
        bob = repository.get_by_username("bob")
        assert bob is not None
        self.assertTrue(bob.must_change_password)

        dialog.user_table.selectRow(1)
        dialog.toggle_required_button.click()
        bob = repository.get_by_username("bob")
        assert bob is not None
        self.assertFalse(bob.must_change_password)

        dialog.user_table.selectRow(1)
        dialog.reset_password_input.setText("secret789")
        dialog.reset_confirm_input.setText("secret789")
        dialog.reset_password_button.click()
        self.assertIsNotNone(repository.verify_user("bob", "secret789"))

        dialog.user_table.selectRow(1)
        dialog.delete_user_button.click()
        self.assertIsNone(repository.get_by_username("bob"))
        self.assertEqual(dialog.user_table.rowCount(), 1)


if __name__ == "__main__":
    unittest.main()
