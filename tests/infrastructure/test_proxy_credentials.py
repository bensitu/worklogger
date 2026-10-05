from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from worklogger.app.use_cases.settings import GetSettingHandler, ProxyPasswordSettings, SetSettingHandler
from worklogger.config.constants import NETWORK_PROXY_PASSWORD_SETTING_KEY, NETWORK_PROXY_PORT_SETTING_KEY
from worklogger.infrastructure.database import MigrationRunner, SQLiteConnectionFactory
from worklogger.infrastructure.repositories import SQLiteAuthRepository, SQLiteSettingsRepository
from worklogger.infrastructure.security.key_store import SystemCredentialStore
from worklogger.infrastructure.security import PBKDF2PasswordHasher, HmacSecretBox, FileMachineKeyProvider
from worklogger.infrastructure.backup import SQLiteBackupService
from worklogger.presentation.viewmodels import SettingsViewModel


class FakeKeyring:
    def __init__(self, *, unavailable=False):
        self.values = {}
        self.unavailable = unavailable

    def get_password(self, service, name):
        if self.unavailable:
            raise RuntimeError("unavailable")
        return self.values.get((service, name))

    def set_password(self, service, name, value):
        if self.unavailable:
            raise RuntimeError("unavailable")
        self.values[service, name] = value

    def delete_password(self, service, name):
        self.values.pop((service, name), None)


class ProxyCredentialTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.factory = SQLiteConnectionFactory(Path(self.directory.name) / "worklog.db")
        MigrationRunner(self.factory).run_pending()
        user = SQLiteAuthRepository(self.factory, password_hasher=PBKDF2PasswordHasher(iterations=1000)).create_user(
            "test-user", "test-only-password", recovery_key=None, is_admin=False,
        )
        self.user_id = user.id
        self.repository = SQLiteSettingsRepository(self.factory)
        self.backend = FakeKeyring()
        self.store = SystemCredentialStore(namespace="test-database", backend=self.backend)
        self.secret_box = HmacSecretBox(FileMachineKeyProvider(Path(self.directory.name) / "test-key"))
        self.passwords = ProxyPasswordSettings(self.repository, self.store, user_id=user.id, secret_box=self.secret_box)
        self.model = SettingsViewModel(
            user_id=user.id, get_handler=GetSettingHandler(self.repository),
            set_handler=SetSettingHandler(self.repository), proxy_password_settings=self.passwords,
        )

    def test_password_round_trip_preserves_whitespace_without_sqlite_plaintext(self):
        password = " synthetic password "
        self.assertTrue(self.model.set_text(NETWORK_PROXY_PASSWORD_SETTING_KEY, password).ok)
        self.assertEqual(self.model.load().value.network_proxy_password, password)
        self.assertIsNone(self.repository.get(self.user_id, NETWORK_PROXY_PASSWORD_SETTING_KEY))
        with self.factory.connection() as connection:
            self.assertFalse(connection.execute("SELECT 1 FROM settings WHERE value=?", (password,)).fetchone())
        self.assertTrue(self.model.set_text(NETWORK_PROXY_PASSWORD_SETTING_KEY, "").ok)
        self.assertEqual(self.model.load().value.network_proxy_password, "")
        self.assertFalse(self.backend.values)

    def test_legacy_password_migrates_only_after_secure_write(self):
        legacy = " legacy synthetic password "
        self.repository.set(self.user_id, NETWORK_PROXY_PASSWORD_SETTING_KEY, legacy)
        with patch.object(self.backend, "set_password", side_effect=RuntimeError("unavailable")):
            self.assertFalse(self.passwords.load().ok)
        self.assertEqual(self.secret_box.decrypt(self.repository.get(self.user_id, NETWORK_PROXY_PASSWORD_SETTING_KEY)), legacy)
        self.assertEqual(self.passwords.load().value, legacy)
        self.assertIsNone(self.repository.get(self.user_id, NETWORK_PROXY_PASSWORD_SETTING_KEY))

    def test_unavailable_keyring_encrypts_legacy_and_excludes_it_from_backup(self):
        self.repository.set(self.user_id, NETWORK_PROXY_PASSWORD_SETTING_KEY, "legacy synthetic password")
        self.backend.unavailable = True
        state = self.model.load().value
        self.assertFalse(state.proxy_password_available)
        self.assertEqual(state.network_proxy_password, "")
        self.assertFalse(self.model.set_text(NETWORK_PROXY_PASSWORD_SETTING_KEY, "new synthetic password").ok)
        stored = self.repository.get(self.user_id, NETWORK_PROXY_PASSWORD_SETTING_KEY)
        self.assertTrue(stored.startswith("enc2:"))
        self.assertEqual(self.secret_box.decrypt(stored), "legacy synthetic password")
        destination = Path(self.directory.name) / "backup.db"
        self.assertTrue(SQLiteBackupService(self.factory).backup_database(destination).ok)
        backup_settings = SQLiteSettingsRepository(SQLiteConnectionFactory(destination))
        self.assertIsNone(backup_settings.get(self.user_id, NETWORK_PROXY_PASSWORD_SETTING_KEY))
        self.assertNotIn(b"legacy synthetic password", destination.read_bytes())

    def test_namespace_and_user_separate_credentials(self):
        other_database = SystemCredentialStore(namespace="other-database", backend=self.backend)
        self.store.set_secret("proxy_password:1", "first synthetic password")
        self.assertIsNone(other_database.get_secret("proxy_password:1").value)
        self.assertIsNone(self.store.get_secret("proxy_password:2").value)

    def test_migration_retries_after_database_cleanup_failure_without_losing_password(self):
        self.repository.set(self.user_id, NETWORK_PROXY_PASSWORD_SETTING_KEY, "legacy synthetic password")
        with patch.object(self.repository, "delete", side_effect=RuntimeError("database unavailable")):
            self.assertFalse(self.passwords.load().ok)
        self.assertEqual(self.secret_box.decrypt(self.repository.get(self.user_id, NETWORK_PROXY_PASSWORD_SETTING_KEY)), "legacy synthetic password")
        self.assertEqual(self.passwords.load().value, "legacy synthetic password")
        self.assertIsNone(self.repository.get(self.user_id, NETWORK_PROXY_PASSWORD_SETTING_KEY))

    def test_non_system_keyring_is_rejected(self):
        import keyring
        insecure = type("PlaintextKeyring", (), {"priority": 10})()
        with patch.object(keyring, "get_keyring", return_value=insecure):
            store = SystemCredentialStore(namespace="test")
            self.assertFalse(store.set_secret("proxy_password", "synthetic password").ok)

    def test_invalid_ports_report_failure_without_changing_saved_port(self):
        self.assertTrue(self.model.set_text(NETWORK_PROXY_PORT_SETTING_KEY, "8080").ok)
        for value in ("abc", "", "-1", "65536", "70000", "80.5"):
            with self.subTest(value=value):
                result = self.model.set_text(NETWORK_PROXY_PORT_SETTING_KEY, value)
                self.assertFalse(result.ok)
                self.assertEqual(result.error.code, "invalid_proxy_port")
                self.assertEqual(self.repository.get(self.user_id, NETWORK_PROXY_PORT_SETTING_KEY), "8080")
        self.assertTrue(self.model.set_text(NETWORK_PROXY_PORT_SETTING_KEY, "0").ok)
        self.assertTrue(self.model.set_text(NETWORK_PROXY_PORT_SETTING_KEY, "65535").ok)
