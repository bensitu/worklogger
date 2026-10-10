from __future__ import annotations

from datetime import date
import tempfile
import unittest

from worklogger.app.commands.auth_commands import (
    AdminResetPasswordCommand,
    CreateManagedUserCommand,
    DeleteManagedUserCommand,
    LoginCommand,
    RegisterUserCommand,
)
from worklogger.app.commands.work_log_commands import SaveWorkLogCommand
from worklogger.app.use_cases.auth import (
    AdminResetPasswordHandler,
    CreateManagedUserHandler,
    DeleteManagedUserHandler,
    LoginHandler,
    RegisterUserHandler,
)
from worklogger.app.use_cases.work_logs import SaveWorkLogHandler
from worklogger.domain.worklog.models import WorkType
from worklogger.infrastructure.database import MigrationRunner, SQLiteConnectionFactory
from worklogger.infrastructure.repositories import SQLiteAuthRepository, SQLiteWorkLogRepository
from worklogger.infrastructure.security import PBKDF2PasswordHasher


class SQLiteUserManagementTests(unittest.TestCase):
    def test_external_account_and_identity_commit_or_roll_back_together(self):
        from worklogger.domain.identity.models import ExternalIdentityProfile
        profile = ExternalIdentityProfile("google", "subject", "person@example.test", "Person", "https://accounts.google.com")
        with self.factory.transaction() as connection:
            connection.execute("CREATE TRIGGER reject_identity BEFORE INSERT ON external_identities BEGIN SELECT RAISE(ABORT, 'identity rejected'); END")
        with self.assertRaises(Exception):
            self.auth.create_identity_account("person", profile)
        self.assertEqual(self.auth.user_count(), 0)
        with self.factory.transaction() as connection:
            connection.execute("DROP TRIGGER reject_identity")
        user, linked = self.auth.create_identity_account("person", profile)
        self.assertFalse(user.local_password_enabled)
        self.assertFalse(user.is_admin)
        self.assertEqual(linked.user_id, user.id)
        repeated = self.auth.create_identity_account("another_name", profile)
        self.assertEqual(repeated[0].id, user.id)
        self.assertEqual(repeated[1].id, linked.id)
        self.assertEqual(self.auth.user_count(), 1)

    def test_recovery_attempts_share_account_lockout_and_preserve_credentials(self):
        from worklogger.app.commands.auth_commands import ResetPasswordCommand
        from worklogger.app.use_cases.auth import ResetPasswordHandler
        from worklogger.infrastructure.repositories.auth_sqlite import SQLiteLoginFailureRepository
        registered = RegisterUserHandler(self.auth).handle(RegisterUserCommand("person", "secret123"))
        failures = SQLiteLoginFailureRepository(self.factory)
        handler = ResetPasswordHandler(self.auth, failures)
        for _attempt in range(5):
            self.assertFalse(handler.handle(ResetPasswordCommand("person", "invalid", "secret456")).ok)
        self.assertIsNotNone(failures.lockout_until("person"))
        valid = ResetPasswordCommand("person", registered.value.recovery_key, "secret456")
        self.assertFalse(handler.handle(valid).ok)
        self.assertIsNotNone(self.auth.verify_user("person", "secret123"))
        failures.clear_failures("person")
        self.assertTrue(handler.handle(valid).ok)
        self.assertIsNone(failures.lockout_until("person"))

    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tempdir.cleanup)
        self.factory = SQLiteConnectionFactory(f"{self._tempdir.name}/worklog.db")
        MigrationRunner(self.factory).run_pending()
        self.auth = SQLiteAuthRepository(
            self.factory,
            password_hasher=PBKDF2PasswordHasher(iterations=1_000),
        )

    def test_admin_reset_clears_remember_token_and_delete_cascades_user_data(self) -> None:
        registered = RegisterUserHandler(self.auth).handle(
            RegisterUserCommand("admin", "secret123")
        )
        self.assertTrue(registered.ok, registered.error)
        assert registered.value is not None
        admin_id = registered.value.user.id
        created = CreateManagedUserHandler(self.auth).handle(
            CreateManagedUserCommand(admin_id, "bob", "secret456")
        )
        self.assertTrue(created.ok, created.error)
        assert created.value is not None
        user_id = created.value.user.id

        remembered = LoginHandler(self.auth).handle(
            LoginCommand("bob", "secret456", remember=True)
        )
        self.assertTrue(remembered.ok, remembered.error)

        reset = AdminResetPasswordHandler(self.auth).handle(
            AdminResetPasswordCommand(admin_id, user_id, "secret789")
        )

        self.assertTrue(reset.ok, reset.error)
        self.assertFalse(LoginHandler(self.auth).handle(LoginCommand("bob", "secret456")).ok)
        relogged = LoginHandler(self.auth).handle(LoginCommand("bob", "secret789"))
        self.assertTrue(relogged.ok, relogged.error)
        assert relogged.value is not None
        self.assertTrue(relogged.value.user.must_change_password)
        with self.factory.connection() as connection:
            row = connection.execute(
                "SELECT remember_token, recovery_key_hash, recovery_salt FROM users WHERE id=?",
                (user_id,),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertIsNone(row["remember_token"])
        self.assertIsNone(row["recovery_key_hash"])
        self.assertIsNone(row["recovery_salt"])
        self.assertEqual(reset.value, "secret789")

        work_logs = SQLiteWorkLogRepository(self.factory)
        saved = SaveWorkLogHandler(work_logs).handle(
            SaveWorkLogCommand(
                user_id=user_id,
                day=date(2026, 5, 14),
                start_time="09:00",
                end_time="18:00",
                break_hours=1.0,
                note="",
                work_type=WorkType.NORMAL.value,
            )
        )
        self.assertTrue(saved.ok, saved.error)
        self.assertEqual(len(work_logs.list_all(user_id)), 1)

        deleted = DeleteManagedUserHandler(self.auth).handle(
            DeleteManagedUserCommand(admin_id, user_id)
        )

        self.assertTrue(deleted.ok, deleted.error)
        self.assertIsNone(self.auth.get_by_id(user_id))
        self.assertEqual(work_logs.list_all(user_id), ())


if __name__ == "__main__":
    unittest.main()
