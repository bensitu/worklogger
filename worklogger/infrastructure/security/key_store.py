"""Encrypted key store adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import base64
import hashlib
import hmac
import os
import secrets
import stat
from typing import Protocol

from worklogger.config.constants import (
    KEYRING_SERVICE_NAME,
    MACHINE_KEY_FILENAME,
    SECRET_SETTING_PREFIX,
)
from worklogger.domain.settings.repositories import SettingsRepository
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result

_ENC_PREFIX = "enc1:"
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
        loaded = self._load()
        if loaded is not None:
            return loaded
        key = secrets.token_bytes(_KEY_BYTES)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            base64.urlsafe_b64encode(key).decode("ascii"),
            encoding="ascii",
        )
        try:
            os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        return key

    def _load(self) -> bytes | None:
        try:
            raw = self.path.read_text(encoding="ascii").strip()
            key = base64.urlsafe_b64decode(raw.encode("ascii"))
        except Exception:
            return None
        return key if len(key) == _KEY_BYTES else None


class HmacSecretBox:
    """Authenticated encryption fallback built from standard library primitives."""

    def __init__(self, key_provider: FileMachineKeyProvider | None = None) -> None:
        self._key_provider = key_provider or FileMachineKeyProvider.default()

    def encrypt(self, value: str) -> str:
        key = self._key_provider.load_or_create()
        nonce = secrets.token_bytes(16)
        plaintext = value.encode("utf-8")
        ciphertext = _xor_bytes(plaintext, _keystream(_derive(key, b"enc"), nonce, len(plaintext)))
        mac = hmac.new(_derive(key, b"mac"), nonce + ciphertext, hashlib.sha256).digest()
        payload = base64.urlsafe_b64encode(nonce + mac + ciphertext).decode("ascii")
        return _ENC_PREFIX + payload

    def decrypt(self, stored: str) -> str:
        if not stored.startswith(_ENC_PREFIX):
            raise ValueError("secret_not_encrypted")
        key = self._key_provider.load_or_create()
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
            return Result.success(self._secret_box.decrypt(stored))
        except ValueError as exc:
            return Result.failure(InfrastructureError(str(exc), str(exc)))

    def set_secret(self, name: str, value: str) -> Result[None]:
        key = self._normalize_name(name)
        if not value:
            return self.delete_secret(key)
        try:
            self._keyring.set_password(self._service_name, key, value)
        except RuntimeError:
            encrypted = self._secret_box.encrypt(value)
            self._settings.set(self._user_id, self._setting_key(key), encrypted)
            return Result.success(None)
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
