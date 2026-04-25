"""Secure key storage — keyring with Fernet-encrypted SQLite fallback.

Priority order
--------------
1. OS keychain via the ``keyring`` library (macOS Keychain, Windows Credential
   Manager, Linux Secret Service / KWallet).  Zero additional dependencies on
   frozen builds that already bundle keyring.
2. Fernet-encrypted value stored in the ``settings`` table.  The symmetric key
   is derived from stable machine identifiers (hostname + MAC address) so the
   ciphertext is useless outside this machine without the key.
3. Plain-text fallback for legacy rows or environments where neither backend
   is available — read-only; new writes always use encryption.

Public API
----------
``get_secret(db, name, user_id)``        → str | None
``set_secret(db, name, value, user_id)`` → None
``delete_secret(db, name, user_id)``     → None

``name`` is an application-level key, e.g. ``"ai_api_key"``.
The actual keychain service name is ``APP_ID`` from constants.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import platform
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from data.db import DB

_log = logging.getLogger(__name__)

# Prefix stored in the DB to distinguish encrypted values from plain-text
# legacy rows written by earlier versions of the app.
_ENC_PREFIX = "enc1:"

# Machine-key derivation.

def _machine_key() -> bytes:
    """Derive a stable 32-byte key from this machine's hardware identifiers.

    Uses hostname + MAC address so the key is consistent across restarts but
    useless on other machines.  Not a substitute for a proper HSM, but raises
    the bar significantly above plain-text storage.
    """
    parts = [platform.node(), str(uuid.getnode())]
    seed = "|".join(parts).encode("utf-8")
    return hashlib.sha256(seed).digest()


def _fernet():
    """Return a ``Fernet`` instance keyed to this machine, or None."""
    try:
        from cryptography.fernet import Fernet
        key = base64.urlsafe_b64encode(_machine_key())
        return Fernet(key)
    except Exception as exc:
        _log.warning("Fernet unavailable: %s", exc)
        return None


# Keyring helpers.

def _keyring_service() -> str:
    try:
        from config.constants import APP_ID
        return APP_ID
    except Exception:
        return "dev.worklogger.app.v1"


def _scoped_name(name: str, user_id: int) -> str:
    return f"user:{user_id}:{name}"


def _keyring_get(name: str, user_id: int) -> str | None:
    try:
        import keyring
        return keyring.get_password(_keyring_service(), _scoped_name(name, user_id))
    except Exception:
        return None


def _keyring_set(name: str, value: str, user_id: int) -> bool:
    try:
        import keyring
        keyring.set_password(_keyring_service(), _scoped_name(name, user_id), value)
        return True
    except Exception:
        return False


def _keyring_delete(name: str, user_id: int) -> None:
    try:
        import keyring
        keyring.delete_password(_keyring_service(), _scoped_name(name, user_id))
    except Exception:
        pass


# Public API.

def get_secret(db: "DB", name: str, user_id: int) -> str:
    """Return the secret for *name*, decrypting if necessary."""
    # 1. Try OS keychain first.
    val = _keyring_get(name, user_id)
    if val is not None:
        return val

    # 2. Fall back to encrypted DB value.
    raw = db.get_setting(name, "", user_id=user_id)
    if not raw:
        return ""
    if raw.startswith(_ENC_PREFIX):
        f = _fernet()
        if f:
            try:
                return f.decrypt(raw[len(_ENC_PREFIX):].encode()).decode()
            except Exception as exc:
                _log.warning("Failed to decrypt %s: %s", name, exc)
                return ""
        # Fernet unavailable — return empty rather than expose ciphertext
        _log.warning("Cannot decrypt %s: cryptography not available", name)
        return ""
    # 3. Plain-text legacy value (written by old app version) — return as-is.
    return raw


def set_secret(db: "DB", name: str, value: str, user_id: int) -> None:
    """Persist *value* for *name* as securely as the environment allows."""
    if not value:
        delete_secret(db, name, user_id)
        return

    # 1. Try OS keychain.
    if _keyring_set(name, value, user_id):
        # Remove any leftover DB entry so there is no stale plaintext copy.
        db.set_setting(name, "", user_id=user_id)
        return

    # 2. Fernet-encrypted DB storage.
    f = _fernet()
    if f:
        ciphertext = f.encrypt(value.encode()).decode()
        db.set_setting(name, _ENC_PREFIX + ciphertext, user_id=user_id)
        return

    # 3. Last resort: plain-text (degraded mode — log a warning).
    _log.warning(
        "Storing %s as plain text: neither keyring nor cryptography is available", name
    )
    db.set_setting(name, value, user_id=user_id)


def delete_secret(db: "DB", name: str, user_id: int) -> None:
    """Remove *name* from both the keychain and the DB."""
    _keyring_delete(name, user_id)
    db.set_setting(name, "", user_id=user_id)
