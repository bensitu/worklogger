"""First-use guidance is initialized only for new accounts and dismissed independently."""

from pathlib import Path
import tempfile
import unittest

from worklogger.app.use_cases.getting_started import GettingStartedService
from worklogger.config.constants import GETTING_STARTED_PENDING_SETTING_KEY
from worklogger.domain.identity.models import ExternalIdentityProfile
from worklogger.infrastructure.database import MigrationRunner, SQLiteConnectionFactory
from worklogger.infrastructure.repositories import SQLiteAuthRepository, SQLiteSettingsRepository
from worklogger.infrastructure.security import PBKDF2PasswordHasher


class GettingStartedTests(unittest.TestCase):
    def test_account_creation_and_dismissal_preserve_other_accounts_and_existing_preferences(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        factory = SQLiteConnectionFactory(Path(directory) / "accounts.db")
        MigrationRunner(factory).run_pending()
        auth = SQLiteAuthRepository(factory, password_hasher=PBKDF2PasswordHasher(iterations=1000))
        settings = SQLiteSettingsRepository(factory)
        existing = auth.create_user("existing", "example-password", recovery_key=None, is_admin=True)
        settings.delete(existing.id, GETTING_STARTED_PENDING_SETTING_KEY)
        registered = auth.register_user("registered", "example-password", recovery_key="synthetic-key")
        managed = auth.create_user("managed", "temporary-password", recovery_key=None,
                                   is_admin=False, must_change_password=True)
        profile = ExternalIdentityProfile("google", "synthetic-subject", issuer="https://accounts.google.com")
        external, _linked = auth.create_identity_account("external", profile)
        self.assertFalse(GettingStartedService(settings, user_id=existing.id).pending().value)
        for user in (registered, managed, external):
            self.assertTrue(GettingStartedService(settings, user_id=user.id).pending().value)
        service = GettingStartedService(settings, user_id=registered.id)
        self.assertTrue(service.dismiss().ok)
        self.assertFalse(GettingStartedService(settings, user_id=registered.id).pending().value)
        self.assertTrue(GettingStartedService(settings, user_id=managed.id).pending().value)
        auth.create_identity_account("external", profile)
        other = GettingStartedService(settings, user_id=external.id)
        other.dismiss()
        auth.create_identity_account("external", profile)
        self.assertFalse(other.pending().value)
