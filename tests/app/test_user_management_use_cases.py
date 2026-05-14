from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import unittest

from worklogger.app.commands.auth_commands import (
    AdminResetPasswordCommand,
    CreateManagedUserCommand,
    DeleteManagedUserCommand,
    RegisterUserCommand,
    SetPasswordChangeRequiredCommand,
)
from worklogger.app.queries.auth_queries import ListUsersQuery
from worklogger.app.use_cases.auth import (
    AdminResetPasswordHandler,
    CreateManagedUserHandler,
    DeleteManagedUserHandler,
    ListUsersHandler,
    RegisterUserHandler,
    SetPasswordChangeRequiredHandler,
)
from worklogger.domain.auth.models import User
from worklogger.domain.auth.policies import generate_recovery_key


class MemoryAuthRepository:
    def __init__(self) -> None:
        self.users: dict[int, tuple[User, str, str]] = {}
        self.remember_tokens: dict[int, tuple[str | None, datetime | None]] = {}
        self.next_id = 1

    def user_count(self) -> int:
        return len(self.users)

    def get_by_id(self, user_id: int) -> User | None:
        entry = self.users.get(user_id)
        return entry[0] if entry is not None else None

    def get_by_username(self, username: str) -> User | None:
        for user, _password, _recovery_key in self.users.values():
            if user.username == username:
                return user
        return None

    def list_users(self) -> tuple[User, ...]:
        return tuple(user for user, _password, _recovery_key in self.users.values())

    def create_user(
        self,
        username: str,
        password: str,
        *,
        recovery_key: str | None,
        is_admin: bool,
        must_change_password: bool = False,
    ) -> User:
        if self.get_by_username(username) is not None:
            raise ValueError("username_exists")
        user = User(
            id=self.next_id,
            username=username,
            is_admin=is_admin,
            must_change_password=must_change_password,
        )
        self.users[user.id] = (user, password, recovery_key or "")
        self.next_id += 1
        return user

    def verify_user(self, username: str, password: str) -> User | None:
        for user, stored_password, _recovery_key in self.users.values():
            if user.username == username and stored_password == password:
                return user
        return None

    def change_password(
        self,
        user_id: int,
        current_password: str,
        new_password: str,
    ) -> str | None:
        entry = self.users.get(user_id)
        if entry is None:
            return None
        user, stored_password, _recovery_key = entry
        if stored_password != current_password:
            return None
        new_recovery_key = generate_recovery_key()
        self.users[user_id] = (
            replace(user, must_change_password=False),
            new_password,
            new_recovery_key,
        )
        return new_recovery_key

    def reset_password_with_recovery(
        self,
        username: str,
        recovery_key: str,
        new_password: str,
    ) -> tuple[User, str] | None:
        for user, _stored_password, stored_recovery_key in self.users.values():
            if user.username == username and stored_recovery_key == recovery_key:
                new_recovery_key = generate_recovery_key()
                updated = replace(user, must_change_password=False)
                self.users[user.id] = (updated, new_password, new_recovery_key)
                return updated, new_recovery_key
        return None

    def reset_password_by_admin(
        self,
        user_id: int,
        new_password: str,
        *,
        must_change_password: bool,
    ) -> str | None:
        entry = self.users.get(user_id)
        if entry is None:
            return None
        user, _stored_password, _recovery_key = entry
        new_recovery_key = generate_recovery_key()
        self.users[user_id] = (
            replace(user, must_change_password=must_change_password),
            new_password,
            new_recovery_key,
        )
        return new_recovery_key

    def set_password_change_required(self, user_id: int, required: bool) -> bool:
        entry = self.users.get(user_id)
        if entry is None:
            return False
        user, password, recovery_key = entry
        self.users[user_id] = (replace(user, must_change_password=required), password, recovery_key)
        if required:
            self.set_remember_token(user_id, None, None)
        return True

    def delete_user(self, user_id: int) -> bool:
        return self.users.pop(user_id, None) is not None

    def set_remember_token(
        self,
        user_id: int,
        stored_token: str | None,
        expires_at: datetime | None,
    ) -> None:
        self.remember_tokens[user_id] = (stored_token, expires_at)

    def get_user_by_remember_token(self, stored_token: str) -> User | None:
        for user_id, (token, _expires_at) in self.remember_tokens.items():
            if token == stored_token:
                return self.get_by_id(user_id)
        return None


class UserManagementUseCaseTests(unittest.TestCase):
    def test_admin_can_create_list_reset_force_change_and_delete_users(self) -> None:
        repository = MemoryAuthRepository()
        registered = RegisterUserHandler(repository).handle(
            RegisterUserCommand("admin", "secret123")
        )
        self.assertTrue(registered.ok, registered.error)
        assert registered.value is not None
        admin_id = registered.value.user.id

        created = CreateManagedUserHandler(repository).handle(
            CreateManagedUserCommand(
                requesting_user_id=admin_id,
                username=" bob ",
                password="secret456",
                is_admin=False,
                must_change_password=True,
            )
        )

        self.assertTrue(created.ok, created.error)
        assert created.value is not None
        self.assertEqual(created.value.user.username, "bob")
        self.assertTrue(created.value.user.must_change_password)
        self.assertTrue(created.value.recovery_key)

        listed = ListUsersHandler(repository).handle(ListUsersQuery(admin_id))
        self.assertTrue(listed.ok, listed.error)
        self.assertEqual([user.username for user in listed.value or ()], ["admin", "bob"])

        reset = AdminResetPasswordHandler(repository).handle(
            AdminResetPasswordCommand(admin_id, created.value.user.id, "secret789")
        )
        self.assertTrue(reset.ok, reset.error)
        self.assertTrue(reset.value)
        self.assertIsNotNone(repository.verify_user("bob", "secret789"))

        updated = SetPasswordChangeRequiredHandler(repository).handle(
            SetPasswordChangeRequiredCommand(admin_id, created.value.user.id, False)
        )
        self.assertTrue(updated.ok, updated.error)
        assert updated.value is not None
        self.assertFalse(updated.value.must_change_password)

        deleted = DeleteManagedUserHandler(repository).handle(
            DeleteManagedUserCommand(admin_id, created.value.user.id)
        )
        self.assertTrue(deleted.ok, deleted.error)
        self.assertIsNone(repository.get_by_username("bob"))

    def test_non_admin_and_self_delete_are_rejected(self) -> None:
        repository = MemoryAuthRepository()
        admin = RegisterUserHandler(repository).handle(
            RegisterUserCommand("admin", "secret123")
        )
        assert admin.value is not None
        user = CreateManagedUserHandler(repository).handle(
            CreateManagedUserCommand(
                admin.value.user.id,
                "bob",
                "secret456",
            )
        )
        assert user.value is not None

        denied = CreateManagedUserHandler(repository).handle(
            CreateManagedUserCommand(user.value.user.id, "carol", "secret789")
        )
        self.assertFalse(denied.ok)
        self.assertEqual(denied.error.code if denied.error else "", "admin_required")

        delete_self = DeleteManagedUserHandler(repository).handle(
            DeleteManagedUserCommand(admin.value.user.id, admin.value.user.id)
        )
        self.assertFalse(delete_self.ok)
        self.assertEqual(delete_self.error.code if delete_self.error else "", "cannot_delete_self")


if __name__ == "__main__":
    unittest.main()
