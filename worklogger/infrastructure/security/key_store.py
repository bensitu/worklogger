"""Encrypted key store adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import base64
import hashlib
import hmac
import os
import secrets
import portalocker
from cryptography.fernet import Fernet, InvalidToken
from worklogger.infrastructure.files import atomic_destination
from typing import Protocol

from worklogger.config.constants import (
    KEYRING_SERVICE_NAME,
    MACHINE_KEY_FILENAME,
    SECRET_SETTING_PREFIX,
    NETWORK_PROXY_PASSWORD_SETTING_KEY,
)
from worklogger.domain.settings.repositories import SettingsRepository
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result

_ENC_PREFIX = "enc1:"
_FERNET_PREFIX = "enc2:"
_KEY_BYTES = 32


class KeyringBackend(Protocol):
    def get_password(self, service: str, name: str) -> str | None:
        ...

    def set_password(self, service: str, name: str, value: str) -> None:
        ...

    def delete_password(self, service: str, name: str) -> None:
        ...


class OptionalKeyringBackend:
    def get_password(self, service: str, name: str) -> str | None:
        try:
            import keyring

            return keyring.get_password(service, name)
        except Exception:
            return None

    def set_password(self, service: str, name: str, value: str) -> None:
        try:
            import keyring

            keyring.set_password(service, name, value)
        except Exception as exc:
            raise RuntimeError("keyring_unavailable") from exc

    def delete_password(self, service: str, name: str) -> None:
        try:
            import keyring

            keyring.delete_password(service, name)
        except Exception:
            pass


class NoKeyringBackend:
    def get_password(self, service: str, name: str) -> str | None:
        return None

    def set_password(self, service: str, name: str, value: str) -> None:
        raise RuntimeError("keyring_unavailable")

    def delete_password(self, service: str, name: str) -> None:
        return None


class SystemCredentialStore:
    """Store credentials in the OS keyring without a plaintext fallback."""

    def __init__(self, *, namespace: str, backend: KeyringBackend | None = None) -> None:
        self._namespace = hashlib.sha256(namespace.encode("utf-8")).hexdigest()
        self._backend = backend

    def _keyring(self):
        if self._backend is not None:
            return self._backend
        import keyring

        backend = keyring.get_keyring()
        candidates = getattr(backend, "backends", (backend,))
        secure_modules = {
            "keyring.backends.Windows", "keyring.backends.macOS",
            "keyring.backends.SecretService", "keyring.backends.libsecret",
            "keyring.backends.kwallet",
        }
        for candidate in candidates:
            if type(candidate).__module__ in secure_modules and candidate.priority > 0:
                return candidate
        raise RuntimeError("credential_storage_unavailable")

    def _name(self, name: str) -> str:
        return f"{self._namespace}:{name}"

    def get_secret(self, name: str) -> Result[str | None]:
        try:
            return Result.success(self._keyring().get_password(KEYRING_SERVICE_NAME, self._name(name)))
        except Exception:
            return Result.failure(InfrastructureError("credential_storage_unavailable", "credential_storage_unavailable"))

    def set_secret(self, name: str, value: str) -> Result[None]:
        try:
            backend = self._keyring()
            if value:
                backend.set_password(KEYRING_SERVICE_NAME, self._name(name), value)
            elif backend.get_password(KEYRING_SERVICE_NAME, self._name(name)) is not None:
                backend.delete_password(KEYRING_SERVICE_NAME, self._name(name))
            return Result.success(None)
        except Exception:
            return Result.failure(InfrastructureError("credential_storage_unavailable", "credential_storage_unavailable"))


@dataclass(frozen=True)
class FileMachineKeyProvider:
    path: Path

    @classmethod
    def default(cls) -> "FileMachineKeyProvider":
        appdata = os.environ.get("APPDATA", "").strip()
        if appdata:
            base = Path(appdata) / "WorkLogger"
        else:
            base = Path.home() / ".config" / "worklogger"
        return cls(base / MACHINE_KEY_FILENAME)

    def load_or_create(self) -> bytes:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with portalocker.Lock(str(self.path) + ".lock", timeout=5):
            loaded = self._load()
            if loaded is not None:
                return loaded
            key = secrets.token_bytes(_KEY_BYTES)
            with atomic_destination(self.path) as temporary:
                temporary.write_text(_encode_machine_key(key), encoding="ascii")
            return key

    def load(self) -> bytes:
        with portalocker.Lock(str(self.path) + ".lock", timeout=5):
            key = self._load()
        if key is None:
            raise ValueError("secret_key_missing")
        return key

    def _load(self) -> bytes | None:
        try:
            raw = self.path.read_text(encoding="ascii").strip()
            if raw.startswith("dpapi:"):
                from worklogger.infrastructure.security.windows_protection import unprotect
                key = unprotect(base64.urlsafe_b64decode(raw[6:].encode("ascii")))
            else:
                key = base64.urlsafe_b64decode(raw.encode("ascii"))
        except FileNotFoundError:
            return None
        except Exception as exc:
            raise ValueError("secret_key_invalid") from exc
        if len(key) != _KEY_BYTES:
            raise ValueError("secret_key_invalid")
        if os.name == "nt" and not raw.startswith("dpapi:"):
            with atomic_destination(self.path) as temporary:
                temporary.write_text(_encode_machine_key(key), encoding="ascii")
        return key


def _encode_machine_key(key: bytes) -> str:
    if os.name == "nt":
        from worklogger.infrastructure.security.windows_protection import protect
        return "dpapi:" + base64.urlsafe_b64encode(protect(key)).decode("ascii")
    return base64.urlsafe_b64encode(key).decode("ascii")


class HmacSecretBox:
    """Fernet encryption with read compatibility for earlier encrypted values."""

    def __init__(self, key_provider: FileMachineKeyProvider | None = None) -> None:
        self._key_provider = key_provider or FileMachineKeyProvider.default()

    def encrypt(self, value: str) -> str:
        key = self._key_provider.load_or_create()
        return _FERNET_PREFIX + Fernet(base64.urlsafe_b64encode(key)).encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, stored: str) -> str:
        if stored.startswith(_FERNET_PREFIX):
            key = self._key_provider.load()
            try:
                return Fernet(base64.urlsafe_b64encode(key)).decrypt(stored[len(_FERNET_PREFIX):].encode("ascii")).decode("utf-8")
            except (InvalidToken, UnicodeError) as exc:
                raise ValueError("secret_authentication_failed") from exc
        if not stored.startswith(_ENC_PREFIX):
            raise ValueError("secret_not_encrypted")
        key = self._key_provider.load()
        try:
            payload = base64.urlsafe_b64decode(stored[len(_ENC_PREFIX):].encode("ascii"))
        except Exception as exc:
            raise ValueError("secret_ciphertext_invalid") from exc
        if len(payload) < 48:
            raise ValueError("secret_ciphertext_invalid")
        nonce = payload[:16]
        mac = payload[16:48]
        ciphertext = payload[48:]
        expected = hmac.new(_derive(key, b"mac"), nonce + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(mac, expected):
            raise ValueError("secret_authentication_failed")
        plaintext = _xor_bytes(ciphertext, _keystream(_derive(key, b"enc"), nonce, len(ciphertext)))
        return plaintext.decode("utf-8")


def protect_legacy_proxy_passwords(connection_factory, secret_box: HmacSecretBox) -> None:
    with connection_factory.transaction(write=True) as connection:
        connection.execute("PRAGMA secure_delete=ON")
        rows = connection.execute("SELECT user_id,value FROM settings WHERE key=? AND value<>''",
                                  (NETWORK_PROXY_PASSWORD_SETTING_KEY,)).fetchall()
        for user_id, value in rows:
            if not value.startswith((_ENC_PREFIX, _FERNET_PREFIX)):
                encrypted = secret_box.encrypt(value)
                connection.execute("UPDATE settings SET value=? WHERE user_id=? AND key=?",
                                   (encrypted, user_id, NETWORK_PROXY_PASSWORD_SETTING_KEY))


class EncryptedSettingsKeyStore:
    """KeyStore implementation with keyring first and encrypted settings fallback."""

    def __init__(
        self,
        settings: SettingsRepository,
        *,
        user_id: int,
        service_name: str = KEYRING_SERVICE_NAME,
        keyring_backend: KeyringBackend | None = None,
        secret_box: HmacSecretBox | None = None,
    ) -> None:
        self._settings = settings
        self._user_id = int(user_id)
        self._service_name = service_name
        self._keyring = keyring_backend or OptionalKeyringBackend()
        self._secret_box = secret_box or HmacSecretBox()

    def get_secret(self, name: str) -> Result[str | None]:
        key = self._normalize_name(name)
        keyring_value = self._keyring.get_password(self._service_name, key)
        if keyring_value is not None:
            return Result.success(keyring_value)
        stored = self._settings.get(self._user_id, self._setting_key(key), None)
        if not stored:
            return Result.success(None)
        try:
            value = self._secret_box.decrypt(stored)
            if stored.startswith(_ENC_PREFIX):
                self._settings.set(self._user_id, self._setting_key(key), self._secret_box.encrypt(value))
            return Result.success(value)
        except ValueError as exc:
            return Result.failure(InfrastructureError(str(exc), str(exc)))
        except Exception:
            return Result.failure(InfrastructureError("credential_storage_unavailable", "credential_storage_unavailable"))

    def set_secret(self, name: str, value: str) -> Result[None]:
        key = self._normalize_name(name)
        if not value:
            return self.delete_secret(key)
        try:
            self._keyring.set_password(self._service_name, key, value)
        except RuntimeError:
            try:
                encrypted = self._secret_box.encrypt(value)
                self._settings.set(self._user_id, self._setting_key(key), encrypted)
                return Result.success(None)
            except Exception:
                return Result.failure(InfrastructureError("credential_storage_unavailable", "credential_storage_unavailable"))
        self._settings.delete(self._user_id, self._setting_key(key))
        return Result.success(None)

    def delete_secret(self, name: str) -> Result[None]:
        key = self._normalize_name(name)
        self._keyring.delete_password(self._service_name, key)
        self._settings.delete(self._user_id, self._setting_key(key))
        return Result.success(None)

    def _normalize_name(self, name: str) -> str:
        if not isinstance(name, str):
            raise TypeError("secret_name_must_be_string")
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("secret_name_required")
        return cleaned

    @staticmethod
    def _setting_key(name: str) -> str:
        return f"{SECRET_SETTING_PREFIX}{name}"


def _derive(key: bytes, purpose: bytes) -> bytes:
    return hmac.new(key, b"worklogger:" + purpose, hashlib.sha256).digest()


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    blocks: list[bytes] = []
    counter = 0
    while sum(len(block) for block in blocks) < length:
        blocks.append(
            hmac.new(
                key,
                nonce + counter.to_bytes(8, "big"),
                hashlib.sha256,
            ).digest()
        )
        counter += 1
    return b"".join(blocks)[:length]


def _xor_bytes(left: bytes, right: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(left, right))
