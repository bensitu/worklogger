"""Shared cryptographic helpers."""

from __future__ import annotations

import base64
from functools import lru_cache
import hashlib
import logging
import os
import platform
import secrets
import stat
import uuid
from pathlib import Path

_log = logging.getLogger(__name__)

_KEY_BYTES = 32
_KEYRING_SERVICE = "dev.worklogger.app.v1"
_KEYRING_ACCOUNT = "machine-key-v2"
_FALLBACK_KEY_FILENAME = ".worklogger_machine_key"


def legacy_machine_key() -> bytes:
    """Return the pre-v3.3.1 deterministic machine key for migration only."""
    seed = f"{platform.node()}|{uuid.getnode()}".encode("utf-8")
    return hashlib.sha256(seed).digest()


@lru_cache(maxsize=1)
def machine_key() -> bytes:
    """Return a stable random 32-byte key stored in the OS keychain or a file."""
    key = _load_keyring_key()
    if key is not None:
        return key
    key = _load_file_key()
    if key is not None:
        _store_keyring_key(key)
        return key
    key = secrets.token_bytes(_KEY_BYTES)
    if _store_keyring_key(key):
        return key
    try:
        _store_file_key(key)
    except OSError:
        _log.warning(
            "Machine key fallback could not be persisted; using an ephemeral "
            "key for this session."
        )
    return key


def _load_keyring_key() -> bytes | None:
    try:
        import keyring

        raw = keyring.get_password(_KEYRING_SERVICE, _KEYRING_ACCOUNT)
    except Exception:
        return None
    return _decode_key(raw)


def _store_keyring_key(key: bytes) -> bool:
    try:
        import keyring

        keyring.set_password(
            _KEYRING_SERVICE,
            _KEYRING_ACCOUNT,
            base64.urlsafe_b64encode(key).decode("ascii"),
        )
        return True
    except Exception:
        return False


def _load_file_key() -> bytes | None:
    try:
        return _decode_key(_fallback_key_path().read_text(encoding="ascii").strip())
    except OSError:
        return None


def _store_file_key(key: bytes) -> None:
    path = _fallback_key_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            base64.urlsafe_b64encode(key).decode("ascii"),
            encoding="ascii",
        )
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError as exc:
        _log.warning("Failed to persist machine key fallback file: %s", exc)
        raise


def _decode_key(raw: str | None) -> bytes | None:
    if not raw:
        return None
    try:
        key = base64.urlsafe_b64decode(raw.encode("ascii"))
    except Exception:
        return None
    return key if len(key) == _KEY_BYTES else None


def _fallback_key_path() -> Path:
    appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        return Path(appdata) / "WorkLogger" / _FALLBACK_KEY_FILENAME
    return Path.home() / ".config" / "worklogger" / _FALLBACK_KEY_FILENAME
