from __future__ import annotations

import os
import unittest
import threading
import time
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

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
from worklogger.presentation.job_runner import ImmediateJobRunner, QtJobRunner
from worklogger.presentation.viewmodels import UserManagementViewModel
from worklogger.domain.shared.result import Result
from worklogger.domain.shared.errors import InfrastructureError


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
    def test_duplicate_display_names_remain_distinguishable_by_login_id(self):
        from dataclasses import replace
        from worklogger.presentation.viewmodels.user_management import UserManagementState, UserListItem
        dialog = UserManagementDialog(_view_model(MemoryAuthRepository(), 1), job_runner=ImmediateJobRunner())
        self.addCleanup(dialog.deleteLater)
        users = (UserListItem(1, "han_meimei", False, False, "Mary"),
                 UserListItem(2, "another_login", False, False, "Mary"))
        dialog.set_state(UserManagementState(users))
        for row, user in enumerate(users):
            dialog.user_table.selectRow(row)
            self.assertEqual(dialog.user_table.item(row, 0).text(), user.username)
            self.assertEqual(dialog.user_table.item(row, 1).text(), "Mary")
            self.assertEqual(dialog.selected_user_label.text(), "Mary")
            self.assertIn(user.username, dialog.selected_login_id_label.text())
        dialog.set_state(UserManagementState((users[0], replace(users[1], display_name="Amy"))))
        self.assertEqual(dialog.selected_user_label.text(), "Amy")

    def test_background_account_changes_keep_ui_responsive_and_selection_explicit(self):
        repository = MemoryAuthRepository()
        admin = RegisterUserHandler(repository).handle(RegisterUserCommand("admin", "secret123"))
        model = _view_model(repository, admin.value.user.id)
        dialog = UserManagementDialog(model, job_runner=ImmediateJobRunner())
        self.addCleanup(dialog.deleteLater)
        dialog.refresh()
        self.assertIsNone(dialog._selected_user_id())
        runner = QtJobRunner(dialog)
        self.addCleanup(lambda: runner.shutdown(wait=True))
        dialog._job_runner = runner
        release = threading.Event()
        self.addCleanup(release.set)
        calls = []
        create = model.create_user
        def delayed(**values):
            calls.append(threading.get_ident())
            release.wait(3)
            return create(**values)
        dialog.username_input.setText("worker")
        dialog.create_password_input.setText("secret456")
        dialog.create_confirm_input.setText("secret456")
        with patch.object(model, "create_user", side_effect=delayed):
            dialog.create_user_button.click()
            self.assertTrue(dialog._busy)
            self.assertFalse(dialog.create_user_button.isEnabled())
            self._app.processEvents()
            release.set()
            deadline = time.monotonic() + 3
            while dialog._busy and time.monotonic() < deadline:
                self._app.processEvents()
                time.sleep(0.005)
        self.assertFalse(dialog._busy)
        self.assertNotEqual(calls, [threading.get_ident()])
        self.assertEqual(dialog._selected_user().username, "worker")
        repository.delete_user(dialog._selected_user_id())
        dialog.set_state(model.load().value)
        self.assertIsNone(dialog._selected_user_id())
        self.assertFalse(dialog.delete_user_button.isEnabled())

    def test_credential_handoff_keeps_its_owner_when_list_refresh_fails(self):
        repository = MemoryAuthRepository()
        admin = RegisterUserHandler(repository).handle(RegisterUserCommand("admin", "secret123"))
        model = _view_model(repository, admin.value.user.id)
        dialog = UserManagementDialog(model, job_runner=ImmediateJobRunner())
        self.addCleanup(dialog.deleteLater)
        dialog.refresh()
        dialog.username_input.setText("new.owner")
        dialog.create_password_input.setText("example-password")
        dialog.create_confirm_input.setText("example-password")
        with patch.object(model, "load", return_value=Result.failure(InfrastructureError("user_list_failed", "user_list_failed"))):
            dialog.create_user_button.click()
        self.assertIsNotNone(repository.get_by_username("new.owner"))
        self.assertIn("new.owner", dialog.recovery_key_caption.text())
        self.assertFalse(dialog.credential_actions.isHidden())
        self.assertTrue(dialog.delete_user_button.isHidden())
        dialog.credential_done_button.click()
        self.assertEqual(dialog.recovery_key_label.text(), "")
        self.assertTrue(dialog.credential_actions.isHidden())

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
        dialog = UserManagementDialog(_view_model(repository, admin.value.user.id), job_runner=ImmediateJobRunner())
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
        dialog.credential_actions.copy_button.click()
        self.assertEqual(QApplication.clipboard().text(), dialog.recovery_key_label.text())
        dialog.credential_done_button.click()

        dialog.user_table.selectRow(1)
        self.assertEqual(dialog.selected_user_label.text(), "bob")
        dialog.password_change_checkbox.click()
        bob = repository.get_by_username("bob")
        assert bob is not None
        self.assertFalse(bob.must_change_password)
        self.assertEqual(dialog.selected_user_label.text(), "bob")

        dialog.user_table.selectRow(1)
        dialog.reset_password_input.setText("secret789")
        dialog.reset_confirm_input.setText("secret789")
        dialog.reset_password_button.click()
        self.assertIsNotNone(repository.verify_user("bob", "secret789"))
        self.assertEqual(dialog.selected_user_label.text(), "bob")
        self.assertEqual(dialog.recovery_key_caption.text(), "Temporary password for bob")
        self.assertEqual(dialog.credential_actions.copy_button.text(), "Copy temporary password")
        dialog.credential_actions.copy_button.click()
        self.assertEqual(QApplication.clipboard().text(), "secret789")
        dialog.user_table.selectRow(0)
        self.assertTrue(dialog.recovery_key_label.isHidden())
        self.assertEqual(dialog.recovery_key_label.text(), "")
        dialog.new_user_button.click()
        self.assertEqual(dialog.operation_tabs.currentIndex(), 1)

        dialog.user_table.selectRow(1)
        self.assertEqual(dialog.operation_tabs.currentIndex(), 0)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            dialog.delete_user_button.click()
        self.assertIsNotNone(repository.get_by_username("bob"))
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            dialog.delete_user_button.click()
        self.assertIsNone(repository.get_by_username("bob"))
        self.assertEqual(dialog.user_table.rowCount(), 1)
        dialog.user_table.clearSelection()
        self.assertFalse(dialog.reset_password_button.isEnabled())
        self.assertFalse(dialog.delete_user_button.isEnabled())
        self.assertFalse(dialog.password_change_checkbox.isEnabled())
        self.assertEqual(dialog.selected_user_label.text(), "Select a user.")
        QApplication.clipboard().clear()


if __name__ == "__main__":
    unittest.main()
