"""Authentication cannot replace credentials revoked during verification."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from worklogger.infrastructure.database import MigrationRunner, SQLiteConnectionFactory
from worklogger.infrastructure.repositories import SQLiteAuthRepository
from worklogger.infrastructure.security import PBKDF2PasswordHasher


class AuthConcurrencyTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.factory = SQLiteConnectionFactory(Path(directory) / "accounts.db")
        MigrationRunner(self.factory).run_pending()
        self.hasher = PBKDF2PasswordHasher(iterations=1000, legacy_iterations=(100,))
        self.auth = SQLiteAuthRepository(self.factory, password_hasher=self.hasher)
        self.user = self.auth.create_user("sample", "original-password", recovery_key="original-recovery", is_admin=False)

    def interrupt_verification(self):
        verify = self.hasher.verify
        reset = []

        def interrupted(*args):
            result = verify(*args)
            if result.matched and not reset:
                reset.append(True)
                self.auth.reset_password_by_admin(self.user.id, "administrator-password", must_change_password=True)
            return result

        return patch.object(self.hasher, "verify", side_effect=interrupted)

    def test_password_login_and_hash_upgrade_do_not_overwrite_a_concurrent_reset(self):
        for upgrade in (False, True):
            with self.subTest(upgrade=upgrade):
                material = self.hasher.hash_password("original-password")
                stored_hash = self.hasher.hash_with_salt("original-password", material.salt_hex,
                                                        iterations=100 if upgrade else 1000)
                with self.factory.transaction() as connection:
                    connection.execute("UPDATE users SET password_hash=?,password_salt=? WHERE id=?",
                                       (stored_hash, material.salt_hex, self.user.id))
                with self.interrupt_verification():
                    self.assertIsNone(self.auth.verify_user("sample", "original-password"))
                self.assertIsNone(self.auth.verify_user("sample", "original-password"))
                self.assertTrue(self.auth.verify_user("sample", "administrator-password").must_change_password)

    def test_password_change_and_recovery_reject_consumed_credentials(self):
        with self.interrupt_verification():
            self.assertIsNone(self.auth.change_password(self.user.id, "original-password", "stale-password"))
        self.assertIsNotNone(self.auth.verify_user("sample", "administrator-password"))
        key = self.auth.change_password(self.user.id, "administrator-password", "original-password")
        self.assertTrue(key)
        with self.interrupt_verification():
            self.assertIsNone(self.auth.reset_password_with_recovery("sample", key, "stale-recovery-password"))
        self.assertIsNotNone(self.auth.verify_user("sample", "administrator-password"))
        self.assertIsNone(self.auth.verify_user("sample", "stale-recovery-password"))
