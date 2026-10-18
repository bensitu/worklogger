"""Account-isolated cloud preferences and atomic credential replacement."""

from dataclasses import replace
import unittest

from tests.infrastructure import test_data_portability_infrastructure as portability
from tests.infrastructure.test_proxy_credentials import FakeKeyring
from worklogger.domain.cloud_backup import BackupConfiguration, BackupCredentials, CONFIG_KEY, STATE_KEY
from worklogger.infrastructure.backup.configuration import CloudBackupConfigurationStore
from worklogger.infrastructure.repositories import SQLiteSettingsRepository
from worklogger.infrastructure.security.key_store import SystemCredentialStore


class CloudConfigurationTests(unittest.TestCase):
    def setUp(self):
        fixture = portability.DataPortabilityInfrastructureTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.factory = fixture.factory
        self.owner = fixture.register_user("cloud-owner")
        self.other = fixture.register_user("other-cloud-owner")
        self.settings, self.keyring = SQLiteSettingsRepository(self.factory), FakeKeyring()
        self.vault = SystemCredentialStore(namespace="synthetic-cloud", backend=self.keyring)
        self.store = CloudBackupConfigurationStore(self.settings, self.vault, self.owner)
        self.configuration = BackupConfiguration(endpoint="https://storage.example")
        self.credentials = BackupCredentials("synthetic-owner", "synthetic-password", passphrase="synthetic-encryption-passphrase")

    def test_credentials_are_kept_out_of_settings_and_isolated_by_account(self):
        self.store.save(self.configuration, self.credentials)
        self.assertEqual(self.store.load(), self.configuration)
        self.assertEqual(self.store.secrets(), self.credentials)
        self.assertNotIn("synthetic-password", str(self.settings.get_all(self.owner)))
        self.assertEqual(CloudBackupConfigurationStore(self.settings, self.vault, self.other).secrets(), BackupCredentials())
        self.keyring.unavailable = True
        with self.assertRaisesRegex(ValueError, "credential_storage_unavailable"):
            self.store.save(self.configuration, self.credentials)

    def test_destination_and_state_change_atomically_with_credential_compensation(self):
        self.store.save(self.configuration, self.credentials)
        original = self.settings.get_all(self.owner)
        with self.factory.transaction() as connection:
            connection.execute("CREATE TRIGGER reject_cloud_state BEFORE UPDATE ON settings "
                "WHEN NEW.key='cloud_backup.state' BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        with self.assertRaises(Exception):
            self.store.save(replace(self.configuration, endpoint="https://other-storage.example"),
                replace(self.credentials, password="replacement-password"))
        self.assertEqual(self.settings.get_all(self.owner), original)
        self.assertEqual(self.store.secrets(), self.credentials)
        self.assertEqual(self.settings.get(self.owner, CONFIG_KEY), original[CONFIG_KEY])

    def test_invalid_transfer_state_requires_manual_review_instead_of_crashing_the_ui(self):
        for raw in ('[]', '{"last_success":"invalid"}', '{"pending_deletions":[1]}', '{"last_error":1}'):
            self.settings.set(self.owner, STATE_KEY, raw)
            with self.assertLogs("worklogger.infrastructure.backup.configuration", level="WARNING"):
                self.assertEqual(self.store.state(), {"last_error": "cloud_configuration_invalid"})
