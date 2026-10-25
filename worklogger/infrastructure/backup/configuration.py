"""Account-scoped cloud settings and OS-protected storage credentials."""

from dataclasses import asdict
import json
import logging
import re
from datetime import datetime

from worklogger.domain.cloud_backup import BackupConfiguration, BackupCredentials, CONFIG_KEY, STATE_KEY


class CloudBackupConfigurationStore:
    def __init__(self, settings, credentials, user_id):
        self.settings, self.credentials, self.user_id = settings, credentials, user_id
        self._secret_name = f"cloud_backup:{user_id}"

    def load(self):
        raw = self.settings.get(self.user_id, CONFIG_KEY)
        try:
            return BackupConfiguration(**json.loads(raw)).validate() if raw else None
        except (ValueError, TypeError, OverflowError, RecursionError, AttributeError):
            raise ValueError("cloud_configuration_invalid") from None

    def secrets(self):
        value = self.credentials.get_secret(self._secret_name)
        if not value.ok:
            raise ValueError("credential_storage_unavailable")
        try:
            return BackupCredentials(**json.loads(value.value)) if value.value else BackupCredentials()
        except (ValueError, TypeError, RecursionError):
            raise ValueError("cloud_credentials_invalid") from None

    def save(self, configuration, credentials):
        configuration.validate()
        if not credentials.username or not credentials.password or ":" in credentials.username:
            raise ValueError("cloud_credentials_invalid")
        if configuration.encrypted and not 12 <= len(credentials.passphrase) <= 1024:
            raise ValueError("cloud_passphrase_invalid")
        try:
            previous = self.load()
        except (ValueError, TypeError):
            previous = None
        old_credentials = self.credentials.get_secret(self._secret_name)
        if not old_credentials.ok:
            raise ValueError("credential_storage_unavailable")
        saved = self.credentials.set_secret(self._secret_name, json.dumps(asdict(credentials)))
        if not saved.ok:
            raise ValueError("credential_storage_unavailable")
        try:
            values = {CONFIG_KEY: json.dumps(asdict(configuration))}
            if previous is None or previous.destination != configuration.destination:
                values[STATE_KEY] = "{}"
            self.settings.set_many(self.user_id, values)
        except Exception:
            self.credentials.set_secret(self._secret_name, old_credentials.value or "")
            raise

    def state(self):
        try:
            state = json.loads(self.settings.get(self.user_id, STATE_KEY) or "{}")
            if not isinstance(state, dict):
                raise ValueError
            for key in ("last_success", "last_restore", "last_attempt"):
                if state.get(key) and datetime.fromisoformat(state[key]).tzinfo is None:
                    raise ValueError
            for key, pattern in (("remote_revision", r"[0-9a-f]{32}"), ("local_digest", r"[0-9a-f]{64}"),
                                 ("last_error", r"(?:cloud|credential)_[a-z_]+")):
                if state.get(key) and not re.fullmatch(pattern, state[key]):
                    raise ValueError
            pending = state.get("pending_deletions", [])
            if not isinstance(pending, list) or any(not re.fullmatch(r"[0-9a-f]{32}", item) for item in pending):
                raise ValueError
            upload = state.get("pending_upload")
            if upload is not None and (not isinstance(upload, dict) or set(upload) != {"revision", "local_digest"}
                    or not isinstance(upload["revision"], str) or not re.fullmatch(r"[0-9a-f]{32}", upload["revision"])
                    or not isinstance(upload["local_digest"], str) or not re.fullmatch(r"[0-9a-f]{64}", upload["local_digest"])):
                raise ValueError
            return state
        except (ValueError, TypeError, OverflowError, RecursionError):
            logging.getLogger(__name__).warning("cloud_backup_state_invalid")
            return {"last_error": "cloud_configuration_invalid"}

    def save_state(self, state):
        self.settings.set(self.user_id, STATE_KEY, json.dumps(state))
