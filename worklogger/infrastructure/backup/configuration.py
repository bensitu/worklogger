"""Account-scoped cloud settings and OS-protected storage credentials."""

from dataclasses import asdict
import json

from worklogger.domain.cloud_backup import BackupConfiguration, BackupCredentials, CONFIG_KEY, STATE_KEY


class CloudBackupConfigurationStore:
    def __init__(self, settings, credentials, user_id):
        self.settings, self.credentials, self.user_id = settings, credentials, user_id
        self._secret_name = f"cloud_backup:{user_id}"

    def load(self):
        raw = self.settings.get(self.user_id, CONFIG_KEY)
        return BackupConfiguration(**json.loads(raw)).validate() if raw else None

    def secrets(self):
        value = self.credentials.get_secret(self._secret_name)
        if not value.ok:
            raise ValueError("credential_storage_unavailable")
        return BackupCredentials(**json.loads(value.value)) if value.value else BackupCredentials()

    def save(self, configuration, credentials):
        configuration.validate()
        if not credentials.username or not credentials.password or ":" in credentials.username:
            raise ValueError("cloud_credentials_invalid")
        if configuration.encrypted and not 12 <= len(credentials.passphrase) <= 1024:
            raise ValueError("cloud_passphrase_invalid")
        previous = self.load()
        old_credentials = self.credentials.get_secret(self._secret_name)
        if not old_credentials.ok:
            raise ValueError("credential_storage_unavailable")
        saved = self.credentials.set_secret(self._secret_name, json.dumps(asdict(credentials)))
        if not saved.ok:
            raise ValueError("credential_storage_unavailable")
        try:
            self.settings.set(self.user_id, CONFIG_KEY, json.dumps(asdict(configuration)))
        except Exception:
            self.credentials.set_secret(self._secret_name, old_credentials.value or "")
            raise
        if previous is None or previous.destination != configuration.destination:
            self.save_state({})

    def state(self):
        return json.loads(self.settings.get(self.user_id, STATE_KEY) or "{}")

    def save_state(self, state):
        self.settings.set(self.user_id, STATE_KEY, json.dumps(state))

    def remove_credentials(self):
        result = self.credentials.set_secret(self._secret_name, "")
        if not result.ok:
            raise ValueError("credential_storage_unavailable")
