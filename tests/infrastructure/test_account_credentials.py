"""Account deletion and numeric ID reuse do not transfer system credentials."""

import tempfile
import unittest
from pathlib import Path

from worklogger.app.commands.auth_commands import DeleteManagedUserCommand
from worklogger.app.use_cases.auth import DeleteManagedUserHandler
from worklogger.infrastructure.database import MigrationRunner, SQLiteConnectionFactory
from worklogger.infrastructure.repositories import SQLiteAuthRepository, SQLiteSettingsRepository
from worklogger.infrastructure.security import PBKDF2PasswordHasher
from worklogger.infrastructure.security.account_credentials import account_credential_namespaces, cleanup_account_credentials
from worklogger.infrastructure.security.key_store import EncryptedSettingsKeyStore, SystemCredentialStore


class MemoryKeyring:
    def __init__(self):
        self.values = {}
        self.fail_delete = False

    def set_password(self, service, name, value):
        self.values[service, name] = value

    def get_password(self, service, name):
        return self.values.get((service, name))

    def delete_password(self, service, name):
        if self.fail_delete:
            raise PermissionError("Synthetic deletion failure")
        self.values.pop((service, name), None)


class AccountCredentialTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(directory) / "accounts.db"
        self.factory = SQLiteConnectionFactory(self.path)
        MigrationRunner(self.factory).run_pending()
        self.auth = SQLiteAuthRepository(self.factory, password_hasher=PBKDF2PasswordHasher(iterations=1000))
        self.settings = SQLiteSettingsRepository(self.factory)
        self.keyring = MemoryKeyring()

    def test_new_accounts_do_not_reuse_deleted_credential_identity(self):
        original = self.auth.create_user("original", "example-password", recovery_key=None, is_admin=False)
        service, namespace = account_credential_namespaces(original.id, self.path)
        store = EncryptedSettingsKeyStore(self.settings, user_id=original.id, service_name=service, keyring_backend=self.keyring)
        self.assertTrue(store.set_secret("ai_api_key", "synthetic-original-key").ok)
        self.assertTrue(self.auth.delete_user(original.id))
        replacement = self.auth.create_user("replacement", "example-password", recovery_key=None, is_admin=False)
        self.assertGreater(replacement.id, original.id)
        new_service, new_namespace = account_credential_namespaces(replacement.id, self.path)
        self.assertNotEqual(new_service, service)
        self.assertEqual(new_namespace, namespace)
        new_store = EncryptedSettingsKeyStore(self.settings, user_id=replacement.id, service_name=new_service, keyring_backend=self.keyring)
        self.assertIsNone(new_store.get_secret("ai_api_key").value)

    def test_cleanup_clears_both_stores_and_failure_preserves_the_account(self):
        admin = self.auth.create_user("admin", "example-password", recovery_key=None, is_admin=True)
        user = self.auth.create_user("target", "example-password", recovery_key=None, is_admin=False)
        service, namespace = account_credential_namespaces(user.id, self.path)
        external = EncryptedSettingsKeyStore(self.settings, user_id=user.id, service_name=service, keyring_backend=self.keyring)
        proxy = SystemCredentialStore(namespace=namespace, backend=self.keyring)
        self.assertTrue(external.set_secret("ai_api_key", "synthetic-key").ok)
        self.assertTrue(proxy.set_secret(f"proxy_password:{user.id}", "synthetic-password").ok)
        handler = DeleteManagedUserHandler(self.auth, cleanup_credentials=lambda identity:
            cleanup_account_credentials(identity, self.path, backend=self.keyring))
        self.keyring.fail_delete = True
        self.assertFalse(handler.handle(DeleteManagedUserCommand(admin.id, user.id)).ok)
        self.assertIsNotNone(self.auth.get_by_id(user.id))
        self.keyring.fail_delete = False
        self.assertTrue(handler.handle(DeleteManagedUserCommand(admin.id, user.id)).ok)
        self.assertEqual(self.keyring.values, {})
        self.assertIsNone(self.auth.get_by_id(user.id))

    def test_existing_scopes_and_password_changes_preserve_credential_identity(self):
        user = self.auth.create_user("existing", "example-password", recovery_key=None, is_admin=False)
        namespace = account_credential_namespaces(user.id, self.path)
        self.auth.reset_password_by_admin(user.id, "changed-password", must_change_password=True)
        self.assertEqual(account_credential_namespaces(user.id, self.path), namespace)
        self.assertEqual(namespace[1], str(self.path.resolve()))
