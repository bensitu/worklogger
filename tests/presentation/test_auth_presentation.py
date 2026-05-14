from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QWidget

from worklogger.app.use_cases.auth import (
    ChangePasswordHandler,
    GetAuthBootstrapStateHandler,
    LoginHandler,
    LoginWithRememberTokenHandler,
    RegisterUserHandler,
    ResetPasswordHandler,
)
from worklogger.config.constants import REMEMBER_TOKEN_HASH_PREFIX
from worklogger.domain.auth.models import User
from worklogger.presentation.auth import (
    AuthController,
    ChangePasswordDialog,
    ChangePasswordDraft,
    LoginDialog,
    LoginDraft,
    RegisterDialog,
    RegisterDraft,
    ResetPasswordDialog,
    ResetPasswordDraft,
)
from worklogger.presentation.viewmodels import AuthViewModel


def _app() -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        return existing
    return QApplication([])


class MemoryAuthRepository:
    def __init__(self) -> None:
        self.users: dict[str, tuple[User, str, str]] = {}
        self.remember_tokens: dict[int, tuple[str | None, datetime | None]] = {}

    def user_count(self) -> int:
        return len(self.users)

    def create_user(
        self,
        username: str,
        password: str,
        *,
        recovery_key: str | None,
        is_admin: bool,
        must_change_password: bool = False,
    ) -> User:
        if username in self.users:
            raise ValueError("username_exists")
        user = User(
            id=len(self.users) + 1,
            username=username,
            is_admin=is_admin,
            must_change_password=must_change_password,
        )
        self.users[username] = (user, password, recovery_key or "")
        return user

    def verify_user(self, username: str, password: str) -> User | None:
        entry = self.users.get(username)
        if entry is None:
            return None
        user, stored_password, _recovery_key = entry
        return user if stored_password == password else None

    def change_password(
        self,
        user_id: int,
        current_password: str,
        new_password: str,
    ) -> str | None:
        for username, (user, stored_password, _recovery_key) in self.users.items():
            if user.id != user_id:
                continue
            if stored_password != current_password:
                return None
            new_recovery_key = f"recovery-{user_id}-changed"
            self.users[username] = (
                replace(user, must_change_password=False),
                new_password,
                new_recovery_key,
            )
            self.remember_tokens[user_id] = (None, None)
            return new_recovery_key
        return None

    def reset_password_with_recovery(
        self,
        username: str,
        recovery_key: str,
        new_password: str,
    ) -> tuple[User, str] | None:
        entry = self.users.get(username)
        if entry is None:
            return None
        user, _stored_password, stored_recovery_key = entry
        if stored_recovery_key != recovery_key:
            return None
        new_recovery_key = f"recovery-{user.id}-reset"
        updated_user = replace(user, must_change_password=False)
        self.users[username] = (updated_user, new_password, new_recovery_key)
        self.remember_tokens[user.id] = (None, None)
        return updated_user, new_recovery_key

    def set_remember_token(
        self,
        user_id: int,
        stored_token: str | None,
        expires_at: datetime | None,
    ) -> None:
        self.remember_tokens[user_id] = (stored_token, expires_at)

    def get_user_by_remember_token(self, stored_token: str) -> User | None:
        for user, _password, _recovery_key in self.users.values():
            token, _expires_at = self.remember_tokens.get(user.id, (None, None))
            if token == stored_token:
                return user
        return None


class MemoryRememberSessionStore:
    def __init__(self, token: str | None = None) -> None:
        self.token = token
        self.saved: list[str] = []
        self.cleared = 0

    def load_token(self):
        from worklogger.domain.shared.result import Result

        return Result.success(self.token)

    def save_token(self, token: str):
        from worklogger.domain.shared.result import Result

        self.token = token
        self.saved.append(token)
        return Result.success(None)

    def clear_token(self):
        from worklogger.domain.shared.result import Result

        self.token = None
        self.cleared += 1
        return Result.success(None)


class AuthPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = _app()

    def auth_view_model(self, repository: MemoryAuthRepository) -> AuthViewModel:
        return AuthViewModel(
            state_handler=GetAuthBootstrapStateHandler(repository),
            login_handler=LoginHandler(repository),
            register_handler=RegisterUserHandler(repository),
            change_password_handler=ChangePasswordHandler(repository),
            remember_token_handler=LoginWithRememberTokenHandler(repository),
            reset_password_handler=ResetPasswordHandler(repository),
        )

    def test_auth_viewmodel_registers_first_user_then_logs_in(self) -> None:
        repository = MemoryAuthRepository()
        view_model = self.auth_view_model(repository)

        mode = view_model.mode()

        self.assertTrue(mode.ok, mode.error)
        assert mode.value is not None
        self.assertEqual(mode.value.mode, "register")

        mismatch = view_model.register(
            username="alice",
            password="secret123",
            password_confirm="secret456",
        )
        self.assertFalse(mismatch.ok)
        self.assertEqual(
            mismatch.error.code if mismatch.error else "",
            "registration_password_mismatch",
        )

        registered = view_model.register(
            username=" alice ",
            password="secret123",
            password_confirm="secret123",
        )

        self.assertTrue(registered.ok, registered.error)
        assert registered.value is not None
        self.assertEqual(registered.value.user.username, "alice")
        self.assertTrue(registered.value.user.is_admin)
        self.assertTrue(registered.value.recovery_key)
        assert view_model.mode().value is not None
        self.assertEqual(view_model.mode().value.mode, "login")

        logged_in = view_model.login(
            username="alice",
            password="secret123",
            remember=True,
        )

        self.assertTrue(logged_in.ok, logged_in.error)
        assert logged_in.value is not None
        self.assertEqual(logged_in.value.user.username, "alice")
        self.assertTrue(logged_in.value.token)
        stored_token, expires_at = repository.remember_tokens[1]
        self.assertIsNotNone(expires_at)
        self.assertTrue(str(stored_token).startswith(REMEMBER_TOKEN_HASH_PREFIX))
        self.assertNotEqual(stored_token, logged_in.value.token)

    def test_login_dialog_emits_login_draft_and_register_request(self) -> None:
        dialog = LoginDialog()
        logins: list[LoginDraft] = []
        register_requested: list[bool] = []
        reset_requested: list[bool] = []
        dialog.login_submitted.connect(logins.append)
        dialog.register_requested.connect(lambda: register_requested.append(True))
        dialog.reset_password_requested.connect(lambda: reset_requested.append(True))

        dialog.username_input.setText("alice")
        dialog.password_input.setText("secret123")
        dialog.remember_check.setChecked(True)
        dialog.login_button.click()
        dialog.register_button.click()
        dialog.reset_password_button.click()

        self.assertEqual(logins, [LoginDraft("alice", "secret123", True)])
        self.assertEqual(register_requested, [True])
        self.assertEqual(reset_requested, [True])
        dialog.set_error("invalid_credentials")
        self.assertEqual(dialog.status_label.text(), "invalid_credentials")

    def test_register_dialog_emits_register_draft_and_shows_recovery_key(self) -> None:
        dialog = RegisterDialog()
        registrations: list[RegisterDraft] = []
        login_requested: list[bool] = []
        dialog.register_submitted.connect(registrations.append)
        dialog.login_requested.connect(lambda: login_requested.append(True))

        dialog.username_input.setText("alice")
        dialog.password_input.setText("secret123")
        dialog.confirm_input.setText("secret123")
        dialog.register_button.click()
        dialog.login_button.click()

        self.assertEqual(registrations, [RegisterDraft("alice", "secret123", "secret123")])
        self.assertEqual(login_requested, [True])
        dialog.set_recovery_key("AAAA-BBBB")
        self.assertFalse(dialog.recovery_key_label.isHidden())
        self.assertFalse(dialog.recovery_key_caption.isHidden())
        self.assertEqual(dialog.recovery_key_label.text(), "AAAA-BBBB")

    def test_reset_password_dialog_emits_draft_and_shows_new_key(self) -> None:
        dialog = ResetPasswordDialog()
        resets: list[ResetPasswordDraft] = []
        login_requested: list[bool] = []
        continue_requested: list[bool] = []
        dialog.reset_submitted.connect(resets.append)
        dialog.login_requested.connect(lambda: login_requested.append(True))
        dialog.continue_requested.connect(lambda: continue_requested.append(True))

        dialog.username_input.setText("alice")
        dialog.recovery_key_input.setText("AAAA-BBBB")
        dialog.password_input.setText("newsecret123")
        dialog.confirm_input.setText("newsecret123")
        dialog.reset_button.click()
        dialog.login_button.click()

        self.assertEqual(
            resets,
            [ResetPasswordDraft("alice", "AAAA-BBBB", "newsecret123", "newsecret123")],
        )
        self.assertEqual(login_requested, [True])
        dialog.mark_complete("CCCC-DDDD")
        dialog.reset_button.click()
        self.assertEqual(continue_requested, [True])
        self.assertFalse(dialog.recovery_key_result_label.isHidden())
        self.assertEqual(dialog.recovery_key_result_label.text(), "CCCC-DDDD")

    def test_change_password_dialog_emits_draft_and_shows_new_key(self) -> None:
        dialog = ChangePasswordDialog()
        changes: list[ChangePasswordDraft] = []
        continue_requested: list[bool] = []
        dialog.change_submitted.connect(changes.append)
        dialog.continue_requested.connect(lambda: continue_requested.append(True))

        dialog.current_password_input.setText("oldsecret123")
        dialog.password_input.setText("newsecret123")
        dialog.confirm_input.setText("newsecret123")
        dialog.change_button.click()

        self.assertEqual(
            changes,
            [ChangePasswordDraft("oldsecret123", "newsecret123", "newsecret123")],
        )
        dialog.mark_complete("EEEE-FFFF")
        dialog.change_button.click()
        self.assertEqual(continue_requested, [True])
        self.assertFalse(dialog.recovery_key_label.isHidden())
        self.assertEqual(dialog.recovery_key_label.text(), "EEEE-FFFF")

    def test_auth_viewmodel_changes_and_resets_passwords(self) -> None:
        repository = MemoryAuthRepository()
        view_model = self.auth_view_model(repository)
        registered = view_model.register(
            username="alice",
            password="secret123",
            password_confirm="secret123",
        )
        self.assertTrue(registered.ok, registered.error)
        assert registered.value is not None

        mismatch = view_model.change_password(
            user_id=registered.value.user.id,
            current_password="secret123",
            new_password="newsecret123",
            password_confirm="different",
        )
        self.assertFalse(mismatch.ok)
        self.assertEqual(mismatch.error.code if mismatch.error else "", "password_change_mismatch")

        changed = view_model.change_password(
            user_id=registered.value.user.id,
            current_password="secret123",
            new_password="newsecret123",
            password_confirm="newsecret123",
        )
        self.assertTrue(changed.ok, changed.error)
        self.assertEqual(changed.value, "recovery-1-changed")

        reset_mismatch = view_model.reset_password(
            username="alice",
            recovery_key="recovery-1-changed",
            new_password="resetsecret123",
            password_confirm="different",
        )
        self.assertFalse(reset_mismatch.ok)
        self.assertEqual(reset_mismatch.error.code if reset_mismatch.error else "", "password_reset_mismatch")

        reset = view_model.reset_password(
            username="alice",
            recovery_key="recovery-1-changed",
            new_password="resetsecret123",
            password_confirm="resetsecret123",
        )
        self.assertTrue(reset.ok, reset.error)
        self.assertEqual(reset.value, "recovery-1-reset")

        logged_in = view_model.login(
            username="alice",
            password="resetsecret123",
        )
        self.assertTrue(logged_in.ok, logged_in.error)

    def test_auth_controller_registers_first_user_before_opening_app(self) -> None:
        repository = MemoryAuthRepository()
        view_model = self.auth_view_model(repository)
        dialogs: list[RegisterDialog] = []

        class ScriptedRegisterDialog(RegisterDialog):
            def __init__(self, parent: QWidget | None = None) -> None:
                super().__init__(parent)
                dialogs.append(self)

            def exec(self) -> int:
                self.username_input.setText("alice")
                self.password_input.setText("secret123")
                self.confirm_input.setText("secret123")
                self.register_button.click()
                self.register_button.click()
                return int(QDialog.DialogCode.Accepted)

        controller = AuthController(
            view_model,
            register_dialog_factory=ScriptedRegisterDialog,
        )

        authenticated = controller.authenticate()

        self.assertTrue(authenticated.ok, authenticated.error)
        assert authenticated.value is not None
        self.assertEqual(authenticated.value.user.username, "alice")
        self.assertTrue(authenticated.value.recovery_key)
        self.assertEqual(dialogs[0].register_button.text(), "Continue")
        self.assertEqual(dialogs[0].recovery_key_label.text(), authenticated.value.recovery_key)

    def test_auth_controller_logs_in_existing_user(self) -> None:
        repository = MemoryAuthRepository()
        view_model = self.auth_view_model(repository)
        registered = view_model.register(
            username="alice",
            password="secret123",
            password_confirm="secret123",
        )
        self.assertTrue(registered.ok, registered.error)

        class ScriptedLoginDialog(LoginDialog):
            def exec(self) -> int:
                self.username_input.setText("alice")
                self.password_input.setText("secret123")
                self.remember_check.setChecked(True)
                self.login_button.click()
                return int(QDialog.DialogCode.Accepted)

        session_store = MemoryRememberSessionStore()
        controller = AuthController(
            view_model,
            login_dialog_factory=ScriptedLoginDialog,
            remember_session_store=session_store,
        )

        authenticated = controller.authenticate()

        self.assertTrue(authenticated.ok, authenticated.error)
        assert authenticated.value is not None
        self.assertEqual(authenticated.value.user.username, "alice")
        self.assertTrue(authenticated.value.remember_token)
        stored_token, expires_at = repository.remember_tokens[1]
        self.assertIsNotNone(expires_at)
        self.assertTrue(str(stored_token).startswith(REMEMBER_TOKEN_HASH_PREFIX))
        self.assertEqual(session_store.saved, [authenticated.value.remember_token])

    def test_auth_controller_uses_remembered_session_before_showing_login(self) -> None:
        repository = MemoryAuthRepository()
        view_model = self.auth_view_model(repository)
        view_model.register(
            username="alice",
            password="secret123",
            password_confirm="secret123",
        )
        logged_in = view_model.login(
            username="alice",
            password="secret123",
            remember=True,
        )
        self.assertTrue(logged_in.ok, logged_in.error)
        assert logged_in.value is not None

        class FailingLoginDialog(LoginDialog):
            def exec(self) -> int:
                raise AssertionError("login dialog should not open")

        controller = AuthController(
            view_model,
            login_dialog_factory=FailingLoginDialog,
            remember_session_store=MemoryRememberSessionStore(logged_in.value.token),
        )

        authenticated = controller.authenticate()

        self.assertTrue(authenticated.ok, authenticated.error)
        assert authenticated.value is not None
        self.assertEqual(authenticated.value.user.username, "alice")

    def test_auth_controller_clears_invalid_remembered_session(self) -> None:
        repository = MemoryAuthRepository()
        view_model = self.auth_view_model(repository)
        view_model.register(
            username="alice",
            password="secret123",
            password_confirm="secret123",
        )
        session_store = MemoryRememberSessionStore("bad-token")

        class ScriptedLoginDialog(LoginDialog):
            def exec(self) -> int:
                self.username_input.setText("alice")
                self.password_input.setText("secret123")
                self.login_button.click()
                return int(QDialog.DialogCode.Accepted)

        controller = AuthController(
            view_model,
            login_dialog_factory=ScriptedLoginDialog,
            remember_session_store=session_store,
        )

        authenticated = controller.authenticate()

        self.assertTrue(authenticated.ok, authenticated.error)
        self.assertGreaterEqual(session_store.cleared, 1)

    def test_auth_controller_resets_password_then_returns_to_login(self) -> None:
        repository = MemoryAuthRepository()
        view_model = self.auth_view_model(repository)
        registered = view_model.register(
            username="alice",
            password="secret123",
            password_confirm="secret123",
        )
        self.assertTrue(registered.ok, registered.error)
        assert registered.value is not None
        recovery_key = registered.value.recovery_key
        login_execs: list[str] = []

        class ScriptedLoginDialog(LoginDialog):
            def exec(self) -> int:
                if not login_execs:
                    login_execs.append("reset")
                    self.reset_password_button.click()
                    return int(QDialog.DialogCode.Rejected)
                login_execs.append("login")
                self.username_input.setText("alice")
                self.password_input.setText("resetsecret123")
                self.login_button.click()
                return int(QDialog.DialogCode.Accepted)

        class ScriptedResetDialog(ResetPasswordDialog):
            def exec(self) -> int:
                self.username_input.setText("alice")
                self.recovery_key_input.setText(recovery_key)
                self.password_input.setText("resetsecret123")
                self.confirm_input.setText("resetsecret123")
                self.reset_button.click()
                self.reset_button.click()
                return int(QDialog.DialogCode.Accepted)

        controller = AuthController(
            view_model,
            login_dialog_factory=ScriptedLoginDialog,
            reset_password_dialog_factory=ScriptedResetDialog,
        )

        authenticated = controller.authenticate()

        self.assertTrue(authenticated.ok, authenticated.error)
        assert authenticated.value is not None
        self.assertEqual(authenticated.value.user.username, "alice")
        self.assertEqual(login_execs, ["reset", "login"])

    def test_auth_controller_requires_password_change_before_session(self) -> None:
        repository = MemoryAuthRepository()
        repository.create_user(
            "alice",
            "oldsecret123",
            recovery_key="AAAA-BBBB",
            is_admin=False,
            must_change_password=True,
        )
        view_model = self.auth_view_model(repository)

        class ScriptedLoginDialog(LoginDialog):
            def exec(self) -> int:
                self.username_input.setText("alice")
                self.password_input.setText("oldsecret123")
                self.remember_check.setChecked(True)
                self.login_button.click()
                return int(QDialog.DialogCode.Accepted)

        class ScriptedChangeDialog(ChangePasswordDialog):
            def exec(self) -> int:
                self.current_password_input.setText("oldsecret123")
                self.password_input.setText("newsecret123")
                self.confirm_input.setText("newsecret123")
                self.change_button.click()
                self.change_button.click()
                return int(QDialog.DialogCode.Accepted)

        controller = AuthController(
            view_model,
            change_password_dialog_factory=ScriptedChangeDialog,
            login_dialog_factory=ScriptedLoginDialog,
        )

        authenticated = controller.authenticate()

        self.assertTrue(authenticated.ok, authenticated.error)
        assert authenticated.value is not None
        self.assertFalse(authenticated.value.user.must_change_password)
        self.assertEqual(authenticated.value.recovery_key, "recovery-1-changed")
        self.assertIsNone(authenticated.value.remember_token)


if __name__ == "__main__":
    unittest.main()
